import ast
import os
import tokenize
from ast import AST, ClassDef
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

import jedi
from jedi.api import Script
from jedi.api.project import Project

from codeanalyzer.schema.py_schema import (
    PyCallable,
    PyCallableParameter,
    PyCallsite,
    PyClass,
    PyClassAttribute,
    PyComment,
    PyImport,
    PyModule,
    PySymbol,
    PyVariableDeclaration,
    PyHammockBlock,
    PyHammockBlockRelation,
)
from codeanalyzer.utils import logger
from codeanalyzer.utils.progress_bar import ProgressBar

from codeanalyzer.hb_tree_sitter.hbt_interface import HammockBlockTreeBuilder as hbt
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock, TSHBRelation


class SymbolTableBuilder:
    """A class for building a symbol table for a Python project."""

    def __init__(self, project_dir: Path | str, virtualenv: Path | str | None) -> None:
        self.project_dir = Path(project_dir)
        if virtualenv is None:
            # If no virtual environment is provided, create a jedi project without an environment.
            self.jedi_project: Project = jedi.Project(path=self.project_dir)
        else:
            # If there is a virtual environment, add its site-packages to sys_path so jedi can find the installed packages.
            self.jedi_project: Project = jedi.Project(
                path=self.project_dir,
                environment_path=Path(virtualenv) / "bin" / "python",
            )

    @staticmethod
    def _infer_type(script: Script, line: int, column: int) -> str:
        """Tries to infer the type at a given position using Jedi."""
        try:
            inference = script.infer(line=line, column=column)
            if inference:
                return inference[0].name  # or .full_name
        except Exception:
            pass
        return None

    @staticmethod
    def _infer_qualified_name(script: Script, line: int, column: int) -> Optional[str]:
        """
        Tries to infer the fully qualified name (e.g., os.path.join) at the given position using Jedi.

        Args:
            script (jedi.Script): The Jedi script object.
            line (int): Line number of the expression.
            column (int): Column offset of the expression.

        Returns:
            Optional[str]: The fully qualified name if available, else None.
        """
        try:
            definitions = script.infer(line=line, column=column)
            if definitions:
                return definitions[0].full_name
        except Exception:
            pass
        return None

    def _module(self, py_file: Path) -> PyModule:
        """Builds a PyModule from a Python file.

        Args:
            py_file (Path): Path to the python file.

        Returns:
            PyModule object for the input file.
        """
        # Get the raw source code from the file
        source = py_file.read_text(encoding="utf-8")
        # Create a Jedi script for the file
        script: Script = Script(path=str(py_file), project=self.jedi_project)
        module = ast.parse(source, filename=str(py_file))
        # Parse the Hammock Block tree for the file
        _, converted_hbt_map, ts_hbt_map = hbt.parse(source, filename=str(py_file), project_base=str(self.project_dir))
        self.converted_hbt_map = converted_hbt_map
        self.ts_hbt_map = ts_hbt_map
        classes = {}
        functions = {}
        
        # TODO as of now the builder cannot handle alternative nested structures like
        # module --> function --> class it only handles
        # module --> class --> methods
        # module --> function --> nested functions
        for node in ast.iter_child_nodes(module):
            if isinstance(node, ClassDef):
                classes.update(self._add_class(node, script, py_file.stem))
            elif isinstance(node, ast.FunctionDef):
                functions.update(self._callables(node, script))
        variables = self._module_variables(module, script)
        py_module = (
            PyModule.builder()
            .file_path(str(py_file))
            .module_name(py_file.stem)
            .comments(self._pycomments(module, source))
            .imports(self._imports(module))
            .variables(variables)
            .classes(classes)
            .functions(functions)
            .hammock_block(self._hb_decomposition(py_file.stem, 
                                            str(py_file), 
                                            local_variables=variables,
                                            accessed_symbols=[],
                                            level="module"))
            .module_hammock_blocks(
                [hb for hb in self.converted_hbt_map["hammock_blocks"]]
                if self.converted_hbt_map is not None
                else []
            )
            .build()
        )
        self._hb_data_relations()
        return py_module

    def _imports(self, module: ast.Module) -> List[PyImport]:
        """
        Extracts all import statements from the module.

        Args:
            module (ast.Module): The AST node representing the module.
            script (Script): The Jedi script object for the module.

        Returns:
            List[PyImport]: A list of PyImport objects representing the import statements.
        """
        imports: List[PyImport] = []

        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        PyImport.builder()
                        .module(alias.name)  # for "import os", alias.name = "os"
                        .name(alias.asname or alias.name)  # name in local scope
                        .alias(alias.name if alias.asname else None)
                        .start_line(getattr(node, "lineno", -1))
                        .end_line(getattr(node, "end_lineno", node.lineno))
                        .start_column(getattr(node, "col_offset", -1))
                        .end_column(getattr(node, "end_col_offset", -1))
                        .build()
                    )

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""  # e.g., from . import x
                for alias in node.names:
                    qualified_module = module_name
                    if node.level:
                        # Handle relative import
                        qualified_module = "." * node.level + (module_name or "")
                    imports.append(
                        PyImport.builder()
                        .module(qualified_module)
                        .name(alias.asname or alias.name)
                        .alias(alias.name if alias.asname else None)
                        .start_line(getattr(node, "lineno", -1))
                        .end_line(getattr(node, "end_lineno", node.lineno))
                        .start_column(getattr(node, "col_offset", -1))
                        .end_column(getattr(node, "end_col_offset", -1))
                        .build()
                    )

        return imports

    def _add_class(
        self, class_node: ast.ClassDef, script: Script, module_name: str) -> Dict[str, PyClass]:
        """Builds a PyClass from a class definition node.

        Args:
            class_node (ast.ClassDef): The AST node representing the class.
            script (Script): The Jedi script object for the module.

        Returns:
            Dict[str, PyClass]: Mapping of class signature to PyClass object.
        """
        # Try resolving full signature with Jedi
        try:
            definitions = script.goto(
                line=class_node.lineno, column=class_node.col_offset
            )
            signature = next(
                (d.full_name for d in definitions if d.type == "class"),
                f"{script.path.__str__().replace('.py', '').replace('/', '.')}.{class_node.name}",
            )
        except Exception:
            signature = (
                f"{script.path.__str__().replace('.py', '').replace('/', '.')}.{class_node.name}",
            )

        code: str = ast.unparse(class_node).strip()
        attributes = self._class_attributes(class_node, script)
        py_class = (
            PyClass.builder()
            .name(class_node.name)
            .signature(signature)
            .start_line(class_node.lineno)
            .end_line(
                getattr(
                    class_node, "end_lineno", class_node.lineno + len(class_node.body)
                )
            )
            .comments(self._pycomments(class_node, code))
            .code(code)
            .base_classes(
                [
                    ast.unparse(base)
                    for base in class_node.bases
                    if isinstance(base, ast.expr)
                ]
            )
            .methods(self._callables(class_node, script))
            .attributes(attributes)
            .inner_classes(
                {
                    k: v
                    for child in class_node.body
                    if isinstance(child, ast.ClassDef)
                    for k, v in self._add_class(child, script).items()
                }
            )
            .hammock_block(
                self._hb_decomposition(module_name + "." + class_node.name, 
                                            str(script.path), 
                                            local_variables=attributes,
                                            accessed_symbols=[],
                                            level="class"))
            .build()
        )

        return {signature: py_class}

    def _hb_decomposition(self, full_qualifier: str, file_path: str,
                            local_variables, accessed_symbols, level, func_parameters=[], call_sites=[]) -> PyHammockBlock:
        """
        Gets the Hammock Block subtree root for a given full qualifier and file path.
        """
        if self.converted_hbt_map is None:
            return None
        hb_identified = None
        for hb in self.converted_hbt_map["hammock_blocks"]:
            if hb.block_full_qualifier == full_qualifier and hb.meta_data.get("source_file") == file_path:
                hb_identified = hb
                break
        if hb_identified is None:
            print(f"No Hammock Block found for {full_qualifier} in {file_path}")
            return None
        else:
            # fill in the local variables and accessed symbols according to levels
            if level == "module":
                children_hbs = self._hb_subtree_blocks_recursive(hb_identified.block_id)
                # only plain expression statements directly under module are eligible for module level variables
                eligible_hbs = []
                for hb in children_hbs:
                    if hb.block_type == "expression_statement" and hb.parent == hb_identified.block_id:
                        eligible_hbs.append(hb)
                for variable in local_variables:
                    name = variable.name
                    start_line = variable.start_line
                    end_line = variable.end_line
                    scope = variable.scope
                    current_placement = hb_identified
                    assert scope == "module"
                    for eligible_hb in eligible_hbs: 
                        if start_line >= eligible_hb.start_line and end_line <= eligible_hb.end_line:
                            if (name in self._ts_local_variables(eligible_hb.block_id)) and (eligible_hb.start_line > current_placement.start_line or eligible_hb.end_line < current_placement.end_line):
                                current_placement = eligible_hb
                    already_exists = False
                    for existing_variable in current_placement.local_variables:
                        if existing_variable.name == name and existing_variable.start_line == start_line and existing_variable.end_line == end_line:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.local_variables.append(variable)
            elif level == "class":
                children_hbs = self._hb_subtree_blocks_recursive(hb_identified.block_id)                
                # only plain expression statements are eligible for module level variables
                eligible_hbs = []
                for hb in children_hbs:
                    if hb.block_type == "expression_statement" and hb.parent == hb_identified.block_id:
                        eligible_hbs.append(hb)
                for variable in local_variables.values():
                    name = variable.name
                    start_line = variable.start_line
                    end_line = variable.end_line
                    current_placement = hb_identified
                    for eligible_hb in eligible_hbs: 
                        if start_line >= eligible_hb.start_line and end_line <= eligible_hb.end_line:
                            if (name in self._ts_local_variables(eligible_hb.block_id)) and (eligible_hb.start_line > current_placement.start_line or eligible_hb.end_line < current_placement.end_line):
                                current_placement = eligible_hb
                    already_exists = False
                    for existing_variable in current_placement.local_variables:
                        if existing_variable.name == name and existing_variable.start_line == start_line and existing_variable.end_line == end_line:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.class_attributes.append(variable)
            elif level == "funcmeth":
                eligible_hbs = self._hb_subtree_blocks_recursive(hb_identified.block_id)
                # process function parameters
                for parameter in func_parameters:
                    name = parameter.name
                    start_line = parameter.start_line
                    end_line = parameter.end_line
                    current_placement = hb_identified
                    already_exists = False
                    for existing_parameters in current_placement.func_parameters:
                        if existing_parameters.name == name and existing_parameters.start_line == start_line and existing_parameters.end_line == end_line:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.func_parameters.append(parameter)
                
                # process local variables
                for variable in local_variables:
                    name = variable.name
                    start_line = variable.start_line
                    end_line = variable.end_line
                    scope = variable.scope
                    current_placement = hb_identified
                    assert scope == "local" or scope == "function"
                    for eligible_hb in eligible_hbs: 
                        if start_line >= eligible_hb.start_line and end_line <= eligible_hb.end_line:
                            if (eligible_hb.start_line > current_placement.start_line or eligible_hb.end_line < current_placement.end_line):
                                if (name not in self._ts_local_variables(eligible_hb.block_id)):
                                    print(f"Warning: Variable {name} not found in original ts hammock block {eligible_hb.block_id}")
                                current_placement = eligible_hb
                    already_exists = False
                    for existing_variable in current_placement.local_variables:
                        if existing_variable.name == name and existing_variable.start_line == start_line and existing_variable.end_line == end_line:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.local_variables.append(variable)
                
                # process accessed symbols
                for symbols in accessed_symbols:
                    name = symbols.name
                    line_number = symbols.lineno
                    kind = symbols.kind
                    current_placement = hb_identified
                    if kind != "variable":
                        continue
                    for eligible_hb in eligible_hbs: 
                        if line_number >= eligible_hb.start_line and line_number <= eligible_hb.end_line:
                            if (name in self._ts_local_variables(eligible_hb.block_id)) and (eligible_hb.start_line > current_placement.start_line or eligible_hb.end_line < current_placement.end_line):
                                current_placement = eligible_hb
                    already_exists = False
                    for existing_symbol in current_placement.accessed_variables:
                        if existing_symbol.name == name and existing_symbol.lineno == line_number:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.accessed_variables.append(symbols)

                # process call sites
                for call_site in call_sites:
                    name = call_site.method_name
                    start_line = call_site.start_line
                    end_line = call_site.end_line
                    current_placement = hb_identified
                    for eligible_hb in eligible_hbs:
                        if line_number >= eligible_hb.start_line and line_number <= eligible_hb.end_line:
                            if (eligible_hb.start_line > current_placement.start_line or eligible_hb.end_line < current_placement.end_line):
                                current_placement = eligible_hb
                    already_exists = False
                    for existing_callsites in current_placement.call_sites:
                        if existing_callsites.method_name == name and existing_callsites.start_line == start_line and existing_callsites.end_line == end_line:
                            already_exists = True
                            break
                    if not already_exists:
                        current_placement.call_sites.append(call_site)
            else:
                raise RuntimeError(f"Unknown Hammock Block level: {level}")           
            return hb_identified
                    
    def _hb_subtree_blocks_recursive(self, block_id: str) -> List[TSHammockBlock]:
        """
        Recursively collects all Hammock Blocks in the subtree starting with the given block ID.
        Returns the root block and all its descendants.
        """
        subtree_blocks = []
        
        # Find the root block first
        root_block = None
        for hb in self.converted_hbt_map["hammock_blocks"]:
            if hb.block_id == block_id:
                root_block = hb
                break
        
        if root_block is None:
            return subtree_blocks
        
        # Add the root block itself
        subtree_blocks.append(root_block)
        
        # Recursively collect all children
        def collect_children(parent_id: str):
            for child in self.converted_hbt_map["hammock_blocks"]:
                if child.parent:
                    for temp_hb in self.converted_hbt_map["hammock_blocks"]:
                        if temp_hb.block_id == child.parent:
                            parent = temp_hb
                            break
                    if parent.block_id == parent_id:
                        subtree_blocks.append(child)
                        collect_children(child.block_id)

        collect_children(block_id)
        return subtree_blocks
    
    def _hb_data_relations(self):
        hbt.build_hb_data_relations(self.converted_hbt_map)
               
    def _hb_call_relations(self, symbol_table: dict[Path, PyModule]):
        # step 1: for each call site, find the targeted function/class definition
        # step 2: create a PyHammockBlockRelation for each call site
        for py_module in symbol_table.values():
            module_hammock_blocks = py_module.module_hammock_blocks
            for block in module_hammock_blocks:
                call_sites = block.call_sites
                for call_site in call_sites:
                    callee_signature = call_site.callee_signature
                    method_name = call_site.method_name
                    callee_block = None
                    
                    # case 1: if the callee_signature is null it is a nested 
                    # function part of the sibiling block
                    if callee_signature is None:
                        # find all sibling blocks
                        sibling_blocks = [
                            hb for hb in module_hammock_blocks
                            if hb.block_id != block.block_id and hb.parent == block.parent
                        ]
                        for sb in sibling_blocks:
                            if sb.block_type == "function_definition" and method_name == sb.block_full_qualifier.split(".")[-1]:
                                callee_block = sb
                                break
                        if callee_block is None:
                            hbt.build_caller_callee_relation(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue
                    
                    # case 2: if the callee_signature is not null and match the method name, but the 
                    # receiver type and expression are both null, module level function call
                    elif callee_signature is not None and call_site.receiver_type is None and call_site.receiver_expr is None and method_name == callee_signature.split(".")[-1]:
                        callee_path, _ = self._resolve_hb_callee_path(callee_signature, list(symbol_table.keys()))
                        py_module = symbol_table.get(Path(callee_path))
                        relevant_blocks = [hb for hb in py_module.module_hammock_blocks]
                        for block in relevant_blocks:
                            if len(block.project_full_qualifier) and block.project_full_qualifier == callee_signature: 
                                callee_block = block
                                break
                        if callee_block is None:
                            hbt.build_caller_callee_relation(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue     
                    
                    # case 3:  if the callee_signature is not null and does not match the method name, but the
                    # receiver type or receiver expression is not null, class level method call
                    elif callee_signature is not None and (call_site.receiver_type is not None or call_site.receiver_expr is not None):
                        real_callee_signature = callee_signature + "." + method_name
                        callee_path, _ = self._resolve_hb_callee_path(real_callee_signature, list(symbol_table.keys()))
                        relevant_blocks = [hb for hb in py_module.module_hammock_blocks]
                        for block in relevant_blocks:
                            if len(block.project_full_qualifier) and block.project_full_qualifier == real_callee_signature: 
                                callee_block = block
                                break
                        if callee_block is None:
                            hbt.build_caller_callee_relation(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue
                    else:
                        logger.error(f"Unexpected call site: {call_site}, investigate")
                        continue     
        return
    
    def _resolve_hb_callee_path(self, callee_signature: str, file_paths:str) -> str:
        relative_paths = [file_path.replace(str(self.project_dir) + "/", "") for file_path in file_paths]
        relative_modules = [os.path.splitext(path)[0].replace("/", ".") for path in relative_paths]
        def longest_common_substring(src, target):
            m = len(src)
            n = len(target)
            dp_table = [[0] * (n + 1) for _ in range(m + 1)]
            res = 0
            for i in range(1, m + 1):
                for j in range(1, n + 1):
                    if src[i - 1] == target[j - 1]:
                        dp_table[i][j] = dp_table[i - 1][j - 1] + 1
                        res = max(res, dp_table[i][j])
                    else:
                        dp_table[i][j] = 0
            return res
        idx = 0
        global_max = 0
        for idx, module in enumerate(relative_modules):
            lcs = longest_common_substring(module, callee_signature)
            if lcs > global_max:
                global_max = lcs
                callee_path = relative_paths[idx]
                callee_module = module
        return callee_path, callee_module
    
    def _ts_local_variables(self, block_id: str) -> List[str]:
        """
        Returns a list of local variable names defined in the Hammock Block with the given ID.
        """
        for hb in self.ts_hbt_map["hammock_blocks"]:
            if hb.block_id == block_id:
                return [hb.split(".")[-1] for hb in hb.local_variables]
        return []
    
    def _callables(self, node: AST, script: Script) -> Dict[str, PyCallable]:
        """
        Builds PyCallable objects from any AST node that may contain functions.

        Args:
            node (AST): The AST node to process (e.g., Module, ClassDef, FunctionDef).
            script (Script): The Jedi script object for the module.

        Returns:
            Dict[str, PyCallable]: A dictionary mapping function/method names to PyCallable objects.
        """
        callables: Dict[str, PyCallable] = {}
        module_path: str = script.path or "<unknown_module>"
        module_name: str = Path(module_path).stem if module_path else "<unknown>"

        def visit(n: AST, class_prefix: str = ""):
            if isinstance(n, ast.FunctionDef):
                method_name = n.name
                start_line = n.lineno
                end_line = getattr(
                    n, "end_lineno", start_line + len(n.body)
                )
                code_start_line = n.body[0].lineno if n.body else start_line
                code: str = ast.unparse(n).strip()
                decorators = [ast.unparse(d) for d in n.decorator_list]

                try:
                    definitions = script.goto(
                        line=start_line, column=n.col_offset
                    )
                except Exception:
                    definitions = []

                signature = next(
                    (d.full_name for d in definitions if d.type == "function"),
                    f"{module_name}.{class_prefix}{method_name}",
                )
                local_variables = self._local_variables(n, script)
                accessed_symbols = self._accessed_symbols(n, script)
                parameters = self._callable_parameters(n, script)
                call_sites = self._call_sites(n, script)
                callables[method_name] = (
                    PyCallable.builder()
                    .name(method_name)
                    .path(script.path.__str__())
                    .signature(signature)
                    .decorators(decorators)
                    .code(code)
                    .start_line(start_line)
                    .end_line(end_line)
                    .code_start_line(code_start_line)
                    .accessed_symbols(accessed_symbols)
                    .call_sites(call_sites)
                    .local_variables(local_variables)
                    .cyclomatic_complexity(self._cyclomatic_complexity(n))
                    .parameters(parameters)
                    .return_type(
                        ast.unparse(n.returns)
                        if n.returns
                        else self._infer_type(
                            script, n.lineno, n.col_offset
                        )
                    )
                    .comments(self._pycomments(n, code))
                    .hammock_block(
                        self._hb_decomposition(signature, 
                                                script.path.__str__(),
                                                local_variables=local_variables,
                                                accessed_symbols=accessed_symbols,
                                                level="funcmeth",
                                                func_parameters=parameters,
                                                call_sites=call_sites))
                    .build()
                )
            for child in ast.iter_child_nodes(n):
                if isinstance(child, ast.FunctionDef):
                    visit(child, class_prefix + n.name + ".")
                elif isinstance(child, ast.ClassDef):
                    visit(child, class_prefix + child.name + ".")
                elif hasattr(child, "body"):
                    visit(child, class_prefix)

        visit(node)
        return callables

    def _pycomments(self, node: ast.AST, source: str) -> List[PyComment]:
        """
        Extracts all PyComment instances (docstring and # comments) from within a specific AST node's body.

        Args:
            node (AST): The AST node (e.g., Module, ClassDef, FunctionDef).
            source (str): Source code of the file.

        Returns:
            List[PyComment]: List of PyComment instances.
        """
        comments: List[PyComment] = []

        # 1. Extract docstring (if any)
        docstring_content = ast.get_docstring(node, clean=False)
        if docstring_content:
            try:
                string_node = node.body[0].value  # type: ignore
                start_line = getattr(string_node, "lineno", getattr(node, "lineno", -1))
                end_line = getattr(string_node, "end_lineno", start_line)
                start_column = getattr(string_node, "col_offset", -1)
                end_column = getattr(
                    string_node, "end_col_offset", start_column + len(docstring_content)
                )
            except Exception:
                start_line = getattr(node, "lineno", -1)
                end_line = getattr(node, "end_lineno", start_line)
                start_column = getattr(node, "col_offset", -1)
                end_column = start_column + len(docstring_content)

            comments.append(
                PyComment.builder()
                .content(docstring_content)
                .start_line(start_line)
                .end_line(end_line)
                .start_column(start_column)
                .end_column(end_column)
                .is_docstring(True)
                .build()
            )

        # 2. Extract # comments scoped within the node's line range
        node_start = getattr(node, "lineno", -1)
        node_end = getattr(node, "end_lineno", node_start)

        tokens = tokenize.generate_tokens(StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                tok_line, tok_col = tok.start
                if node_start <= tok_line <= node_end:
                    comment_text = tok.string.lstrip("#").strip()
                    comments.append(
                        PyComment.builder()
                        .content(comment_text)
                        .start_line(tok_line)
                        .end_line(tok_line)
                        .start_column(tok_col)
                        .end_column(tok_col + len(tok.string))
                        .is_docstring(False)
                        .build()
                    )

        return comments

    def _class_attributes(
        self, ast_node: ast.AST, script: Script
    ) -> Dict[str, PyClassAttribute]:
        """
        Extracts class attributes from the class definition.

        Args:
            ast_node (AST): The AST node representing the class.
            script (Script): The Jedi script object for the module.

        Returns:
            Dict[str, PyClassAttribute]: A dictionary mapping attribute names to their metadata.
        """
        attributes: Dict[str, PyClassAttribute] = {}

        for stmt in ast_node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        attributes[target.id] = (
                            PyClassAttribute.builder()
                            .name(target.id)
                            .type(
                                self._infer_type(
                                    script, target.lineno, target.col_offset
                                )
                            )
                            .start_line(getattr(target, "lineno", -1))
                            .end_line(getattr(stmt, "end_lineno", stmt.lineno))
                            .build()
                        )

            elif isinstance(stmt, ast.AnnAssign):
                target = stmt.target
                if isinstance(target, ast.Name):
                    attributes[target.id] = (
                        PyClassAttribute.builder()
                        .name(target.id)
                        .type(
                            ast.unparse(stmt.annotation)
                            if stmt.annotation
                            else self._infer_type(
                                script, target.lineno, target.col_offset
                            )
                        )
                        .start_line(getattr(target, "lineno", -1))
                        .end_line(getattr(stmt, "end_lineno", stmt.lineno))
                        .build()
                    )
            # We may also encounter `__slots__` in class definitions.
            # This is a special case where attributes are defined in a list or tuple.
            # class Foo:
            #     __slots__ = ('x', 'y')
            #
            # Doing so restricts dynamic attribute assignment.
            # This means that you can do
            # Foo.x = 1
            # Foo.y = 2
            # But, not
            # Foo.z = 3
            elif isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__slots__" for t in stmt.targets
            ):
                if isinstance(stmt.value, (ast.List, ast.Tuple)):
                    for elt in stmt.value.elts:
                        if isinstance(elt, (ast.Str, ast.Constant)):
                            value = elt.s if isinstance(elt, ast.Str) else elt.value
                            attributes[value] = (
                                PyClassAttribute.builder()
                                .name(value)
                                .type("slot")
                                .start_line(getattr(stmt, "lineno", -1))
                                .end_line(getattr(stmt, "end_lineno", stmt.lineno))
                                .build()
                            )

        return attributes

    def _callable_parameters(
        self, fn_node: ast.FunctionDef, script: Script
    ) -> List[PyCallableParameter]:
        """
        Extracts callable parameters from the function definition.
        """

        # Pull full name from Jedi (e.g., mypkg.module.MyClass.my_func)
        try:
            definitions = script.goto(line=fn_node.lineno, column=fn_node.col_offset)
            full_name = next(
                (d.full_name for d in definitions if d.type == "function"), None
            )
        except Exception:
            full_name = None

        class_name = (
            full_name.split(".")[-2] if full_name and "." in full_name else None
        )

        params: List[PyCallableParameter] = []
        args = fn_node.args

        def resolve_type(arg_node: ast.arg) -> Optional[str]:
            if arg_node.annotation:
                return ast.unparse(arg_node.annotation)
            if arg_node.arg in {"self", "cls"} and class_name:
                return class_name
            return self._infer_type(script, arg_node.lineno, arg_node.col_offset)

        def build_param(
            arg_node: ast.arg, default: Optional[ast.expr]
        ) -> PyCallableParameter:
            return (
                PyCallableParameter.builder()
                .name(arg_node.arg)
                .type(resolve_type(arg_node))
                .default_value(ast.unparse(default) if default else None)
                .start_line(getattr(arg_node, "lineno", -1))
                .end_line(
                    getattr(arg_node, "end_lineno", getattr(arg_node, "lineno", -1))
                )
                .start_column(getattr(arg_node, "col_offset", -1))
                .end_column(getattr(arg_node, "end_col_offset", -1))
                .build()
            )

        # Fill out all parameter types
        for arg in getattr(args, "posonlyargs", []):
            params.append(build_param(arg, None))

        default_start = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            default = args.defaults[i - default_start] if i >= default_start else None
            params.append(build_param(arg, default))

        if args.vararg:
            params.append(build_param(args.vararg, None))

        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            params.append(build_param(arg, default))

        if args.kwarg:
            params.append(build_param(args.kwarg, None))

        return params

    def _accessed_symbols(self, fn_node: ast.FunctionDef, script: Script) -> List[str]:
        """Analyzes the function body to extract all accessed symbols."""
        symbols = []
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                symbol = self._symbol_from_name_node(
                    node, script, enclosing_scope="local"
                )
                symbols.append(symbol)
        return symbols

    def _call_sites(self, fn_node: ast.FunctionDef, script: Script) -> List[PyCallsite]:
        """
        Finds all call sites made from within the function using Jedi for type inference.

        Args:
            fn_node (ast.FunctionDef): The AST node representing the function.
            script (jedi.Script): The Jedi script object.

        Returns:
            List[PyCallsite]: A list of PyCallsite objects representing each call.
        """
        call_sites: List[PyCallsite] = []

        for node in ast.walk(fn_node):
            if not isinstance(node, ast.Call):
                continue

            func_expr = node.func

            method_name = "<unknown>"
            callee_signature = self._infer_qualified_name(
                script, node.lineno, node.col_offset
            )
            return_type = self._infer_type(script, node.lineno, node.col_offset)

            receiver_expr = None
            receiver_type = None
            if isinstance(func_expr, ast.Attribute):
                receiver_expr = ast.unparse(func_expr.value)
                receiver_type = self._infer_type(
                    script, func_expr.value.lineno, func_expr.value.col_offset
                )
                method_name = func_expr.attr
            elif isinstance(func_expr, ast.Name):
                method_name = func_expr.id

            argument_types = [
                self._infer_type(script, arg.lineno, arg.col_offset)
                or type(arg).__name__
                for arg in node.args
            ]

            call_sites.append(
                PyCallsite.builder()
                .method_name(method_name)
                .receiver_expr(receiver_expr)
                .receiver_type(receiver_type)
                .argument_types(argument_types)
                .return_type(return_type)
                .callee_signature(callee_signature)
                .is_constructor_call(method_name == "__init__")
                .start_line(getattr(node, "lineno", -1))
                .start_column(getattr(node, "col_offset", -1))
                .end_line(getattr(node, "end_lineno", -1))
                .end_column(getattr(node, "end_col_offset", -1))
                .build()
            )

        return call_sites

    def _module_variables(
        self, module: ast.Module, script: Script
    ) -> List[PyVariableDeclaration]:
        """
        Extracts all variable declarations at the module level (excluding functions/classes).
        Includes variables in `if __name__ == "__main__"` blocks.

        Args:
            module (ast.Module): The root module AST.
            script (jedi.Script): For type inference.

        Returns:
            List[PyVariableDeclaration]
        """
        module_vars = []

        def is_nested_in_function_or_class(n: ast.AST) -> bool:
            while hasattr(n, "parent"):
                n = n.parent
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    return True
            return False

        # Add parent pointers (needed for scope check)
        for node in ast.walk(module):
            for child in ast.iter_child_nodes(node):
                child.parent = node  # type: ignore

        for node in ast.walk(module):
            if isinstance(node, ast.Assign):
                if is_nested_in_function_or_class(node):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        module_vars.append(
                            PyVariableDeclaration.builder()
                            .name(target.id)
                            .type(
                                self._infer_type(
                                    script, target.lineno, target.col_offset
                                )
                            )
                            .initializer(
                                ast.unparse(node.value) if node.value else None
                            )
                            .value(None)
                            .scope("module")
                            .start_line(getattr(target, "lineno", -1))
                            .end_line(
                                getattr(node, "end_lineno", getattr(node, "lineno", -1))
                            )
                            .start_column(getattr(target, "col_offset", -1))
                            .end_column(getattr(target, "end_col_offset", -1))
                            .build()
                        )

            elif isinstance(node, ast.AnnAssign):
                if is_nested_in_function_or_class(node):
                    continue
                target = node.target
                if isinstance(target, ast.Name):
                    module_vars.append(
                        PyVariableDeclaration.builder()
                        .name(target.id)
                        .type(
                            ast.unparse(node.annotation)
                            if node.annotation
                            else self._infer_type(script, node.lineno, node.col_offset)
                        )
                        .initializer(ast.unparse(node.value) if node.value else None)
                        .value(None)
                        .scope("module")
                        .start_line(getattr(target, "lineno", -1))
                        .end_line(
                            getattr(node, "end_lineno", getattr(node, "lineno", -1))
                        )
                        .start_column(getattr(target, "col_offset", -1))
                        .end_column(getattr(target, "end_col_offset", -1))
                        .build()
                    )

        return module_vars

    def _local_variables(
        self, fn_node: ast.FunctionDef, script: Script
    ) -> List[PyVariableDeclaration]:
        """
        Extracts all local variables and instance attribute assignments from the function.

        Args:
            fn_node (ast.FunctionDef): The function AST node.
            script (jedi.Script): Jedi script for type inference.

        Returns:
            List[PyVariableDeclaration]: All variables assigned inside this function.
        """
        local_vars: List[PyVariableDeclaration] = []

        for node in ast.walk(fn_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    # This one handles simple variable assignments
                    if isinstance(target, ast.Name):
                        local_vars.append(
                            PyVariableDeclaration.builder()
                            .name(target.id)
                            .type(
                                self._infer_type(
                                    script, target.lineno, target.col_offset
                                )
                            )
                            .initializer(
                                ast.unparse(node.value) if node.value else None
                            )
                            .value(None)
                            .scope("function")
                            .start_line(getattr(target, "lineno", -1))
                            .end_line(
                                getattr(node, "end_lineno", getattr(node, "lineno", -1))
                            )
                            .start_column(getattr(target, "col_offset", -1))
                            .end_column(getattr(target, "end_col_offset", -1))
                            .build()
                        )
                    # This handles instance attribute assignments like self.attr = value
                    elif (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        local_vars.append(
                            PyVariableDeclaration.builder()
                            .name(target.attr)
                            .type(
                                self._infer_type(
                                    script, target.lineno, target.col_offset
                                )
                            )
                            .initializer(
                                ast.unparse(node.value) if node.value else None
                            )
                            .value(None)
                            .scope("class")
                            .start_line(getattr(target, "lineno", -1))
                            .end_line(
                                getattr(node, "end_lineno", getattr(node, "lineno", -1))
                            )
                            .start_column(getattr(target, "col_offset", -1))
                            .end_column(getattr(target, "end_col_offset", -1))
                            .build()
                        )

            elif isinstance(node, ast.AnnAssign):
                target = node.target
                annotation_str = (
                    ast.unparse(node.annotation)
                    if node.annotation
                    else self._infer_type(script, node.lineno, node.col_offset)
                )
                initializer_str = ast.unparse(node.value) if node.value else None
                # Annotated local variable: x: int = SOME_VALUE
                if isinstance(target, ast.Name):
                    local_vars.append(
                        PyVariableDeclaration.builder()
                        .name(target.id)
                        .type(annotation_str)
                        .initializer(initializer_str)
                        .value(None)
                        .scope("function")
                        .start_line(getattr(target, "lineno", -1))
                        .end_line(
                            getattr(node, "end_lineno", getattr(node, "lineno", -1))
                        )
                        .start_column(getattr(target, "col_offset", -1))
                        .end_column(getattr(target, "end_col_offset", -1))
                        .build()
                    )
                # Annotated instance attribute: self.attr: int = SOME_VALUE
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    local_vars.append(
                        PyVariableDeclaration.builder()
                        .name(target.attr)
                        .type(annotation_str)
                        .initializer(initializer_str)
                        .value(None)
                        .scope("class")
                        .start_line(getattr(target, "lineno", -1))
                        .end_line(
                            getattr(node, "end_lineno", getattr(node, "lineno", -1))
                        )
                        .start_column(getattr(target, "col_offset", -1))
                        .end_column(getattr(target, "end_col_offset", -1))
                        .build()
                    )

        return local_vars

    def _cyclomatic_complexity(self, fn_node: ast.FunctionDef) -> int:
        """
        Computes the cyclomatic complexity of a function based on its control flow constructs.

        Args:
            fn_node (ast.FunctionDef): AST node representing the function.

        Returns:
            int: Cyclomatic complexity score (>= 1).
        """
        complexity = 1  # Base path

        for node in ast.walk(fn_node):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                complexity += 1

            elif isinstance(node, ast.BoolOp):
                # Count 'and' / 'or' as individual decision points
                complexity += len(node.values) - 1

            elif isinstance(node, ast.IfExp):
                # Ternary conditional: x if cond else y
                complexity += 1

            elif isinstance(node, ast.ExceptHandler):
                # Try and catch statement
                complexity += 1

            # TODO: I am also counting 'assert' or 'return' or 'yield' as complexity bumps
            elif isinstance(node, (ast.Assert, ast.Return, ast.Yield, ast.YieldFrom)):
                complexity += 1

        return complexity

    def _symbol_from_name_node(
        self,
        name_node: ast.Name,
        script: Optional[Script] = None,
        enclosing_scope: Optional[str] = None,  # e.g. "function", "class", "module"
    ) -> PySymbol:
        """
        Builds a PySymbol object from a given ast.Name node.

        Args:
            name_node (ast.Name): The AST node representing the variable.
            script (Optional[jedi.Script]): Jedi script for type/scope inference.
            enclosing_scope (Optional[str]): The logical scope the name is inside of.

        Returns:
            PySymbol: A fully built symbol object.
        """
        name = name_node.id
        lineno = getattr(name_node, "lineno", -1)
        col_offset = getattr(name_node, "col_offset", -1)
        is_builtin = name in dir(__builtins__)
        qname = None
        inferred_type = None
        kind = "variable"
        scope = enclosing_scope or "local"

        if script:
            try:
                definitions = script.infer(line=lineno, column=col_offset)
                if definitions:
                    d = definitions[0]
                    inferred_type = d.name
                    qname = d.full_name
                    if d.type == "function":
                        kind = "function"
                    elif d.type == "module":
                        kind = "module"
                        scope = "global"
                    elif d.type == "class":
                        kind = "class"
                    elif d.type == "param":
                        kind = "parameter"
            except Exception:
                pass

        return (
            PySymbol.builder()
            .name(name)
            .scope(scope)
            .kind(kind)
            .type(inferred_type)
            .qualified_name(qname)
            .is_builtin(is_builtin)
            .lineno(lineno)
            .col_offset(col_offset)
            .build()
        )

    def build(self) -> Dict[str, PyModule]:
        """Builds the symbol table for the project.

        This method scans the project directory, identifies Python files,
        and constructs a symbol table containing information about classes,
        functions, and variables defined in those files.
        """
        symbol_table: Dict[str, PyModule] = {}
        # Get all Python files first to show accurate progress
        py_files = [
            py_file
            for py_file in self.project_dir.rglob("*.py")
            if "site-packages"
            not in py_file.resolve().__str__()  # exclude site-packages
            and ".venv"
            not in py_file.resolve().__str__()  # exclude virtual environments
            and ".codeanalyzer"
            not in py_file.resolve().__str__()  # exclude internal cache directories
        ]

        with ProgressBar(len(py_files), "Building symbol table") as progress:
            for py_file in py_files:
                try:
                    py_module = self._module(py_file)
                    symbol_table[str(py_file)] = py_module
                except Exception as e:
                    logger.error(f"Failed to process {py_file}: {e}")
                    raise e
                progress.advance()
            self._hb_call_relations(symbol_table)
            progress.finish("✅ Symbol table generation complete.")

        return symbol_table
