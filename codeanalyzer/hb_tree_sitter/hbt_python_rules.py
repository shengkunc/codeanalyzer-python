from tree_sitter import Language, Parser, Tree, Node, Point
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock, TSHBRelation
from typing import NewType, Dict, Callable
from functools import wraps
from codeanalyzer.hb_tree_sitter.hbt_dispatcher import ts_node_overload
from codeanalyzer.hb_tree_sitter.codeql_utils.codeql_interfaces import CodeQLUtils
from codeanalyzer.hb_tree_sitter.scalpel_utils.scalpel_interfaces import ScalpelUtils
import os


class PythonTSHBParsingRules:
    """
    Tree-sitter parsing rules for Python code, using the TSHammockBlock and Relation class.
    """
    def __init__(self, source_code_dir_list, src_file_to_dir_map, artifact_dir=None, exclude_self=True, cg_backend="default"):
        self.supported_block_type = {
                'if_statement', 'for_statement', 'while_statement', 'try_statement',
                'with_statement', 'match_statement', 'function_definition', 'class_definition'
            }
        self.exclude_self = exclude_self
        self.cg_backend = cg_backend
        self.src_file_to_dir_map = src_file_to_dir_map
        if cg_backend == "codeql":
            self.cg_backend_utils = CodeQLUtils
            self.py_codeql_databases = self.cg_backend_utils.construct_codeql_database_from_list(source_code_dir_list, artifact_dir, language="python")
        elif cg_backend == "scalpel":
            self.cg_backend_utils = ScalpelUtils
            self.py_scalpel_callgraphs = self.cg_backend_utils.construct_scalpel_callgraphs_from_list(source_code_dir_list)
        else:
            raise ValueError(f"Unsupported cg_backend: {cg_backend}. Supported backends are: codeql.")

    @ts_node_overload
    def parse_ts_node(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:
        """Entry point for parsing - dispatches to registered handlers"""
        pass  # Body is replaced by per module dispatcher

    def _parse_default(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:
        """Fallback for unhandled node types"""
        print(f"[PYTHON DEFAULT] Parsing unhandled node type: {node.type}")
        return None, []
    
    @parse_ts_node.register("module")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python module (top-level node)"""
        print(f"[PYTHON] Dispatched to parse_module for node: {node.type}")
        print(f"[PYTHON] Module at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        source_dir = self.src_file_to_dir_map[source_file]
        relative_path = source_file.replace(source_dir + os.sep, "")
        basename_no_ext = os.path.splitext(relative_path)[0]
        basename_no_ext = basename_no_ext.replace(os.sep, ".")  # Convert path separators to dots
        hammock_block.block_full_qualifier = basename_no_ext
        return hammock_block, []
    
    @parse_ts_node.register("import_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python import_statement"""
        print(f"[PYTHON] Dispatched to parse_import_statement for node: {node.type}")
        print(f"[PYTHON] Import statement at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        identifers, variables, strings = self._find_identifiers_locals_strings_in_subtree(node)
        hammock_block.imported_packages.extend(variables)
        assert len(identifers) == 0, "Function and class identifiers should not be present in import statements"
        assert len(strings) == 0, "Strings should not be present in import statements"
        return hammock_block, []
    
    @parse_ts_node.register("import_from_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python import_from_statement"""
        print(f"[PYTHON] Dispatched to parse_import_statement for node: {node.type}")
        print(f"[PYTHON] Import from statement at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        identifers, variables, strings = self._find_identifiers_locals_strings_in_subtree(node)
        hammock_block.imported_packages.extend(variables)
        assert len(identifers) == 0, "Variables should not be present in import statements"
        assert len(strings) == 0, "Strings should not be present in import statements"
        return hammock_block, []
    
    @parse_ts_node.register("comment")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested! BUT need a better way to associate comments with blocks
        """Parse Python comment"""
        print(f"[PYTHON] Dispatched to parse_comment for node: {node.type}")
        print(f"[PYTHON] Comment at line {node.start_point.row + 1}")
        comment = node.text.decode("utf-8")
        current_parent = node.parent
        while current_parent and (current_parent.id not in block_map):
            current_parent = current_parent.parent 
        block_map[current_parent.id].comments.append(comment)
        return None, []
    
    @parse_ts_node.register("call")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: 
        """Parse Python callsite"""
        print(f"[PYTHON] Dispatched to parse_callsite for node: {node.type}")
        print(f"[PYTHON] Callsite at line {node.start_point.row + 1}")
        function_call_tree = node.child_by_field_name("function")
        full_call = function_call_tree.text.decode("utf-8")
        current_parent = node.parent
        while current_parent and (current_parent.id not in block_map):
            current_parent = current_parent.parent 
        block_map[current_parent.id].local_callsites.append([function_call_tree, full_call])
        return None, []
    
    @parse_ts_node.register("class_definition")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python class_definition"""
        print(f"[PYTHON] Dispatched to parse_class_definition for node: {node.type}")
        print(f"[PYTHON] Class definition at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        name_node = node.child_by_field_name("name")
        if name_node and name_node.type == "identifier":
            hammock_block.local_identifiers.append(name_node.text.decode("utf-8"))
        superclasses_node = node.child_by_field_name("superclasses")
        if superclasses_node and superclasses_node.type == "argument_list":
            for identifier_node in superclasses_node.named_children:
                if identifier_node.type == "identifier":
                    print(f"[PYTHON] Found superclass identifier: {identifier_node.text.decode('utf-8')}")
                    hammock_block.local_identifiers.append(identifier_node.text.decode("utf-8"))
        current_parent = node.parent
        while current_parent:
            if current_parent.id in block_map and len(block_map[current_parent.id].block_full_qualifier):
                break
            current_parent = current_parent.parent
        hammock_block.block_full_qualifier = block_map[current_parent.id].block_full_qualifier + "." + name_node.text.decode("utf-8") if name_node else ""
        return hammock_block, []
    
    @parse_ts_node.register("function_definition")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python function_definition"""
        print(f"[PYTHON] Dispatched to parse_function_definition for node: {node.type}")
        print(f"[PYTHON] Function definition at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        name_node = node.child_by_field_name("name")
        if name_node and name_node.type == "identifier":
            hammock_block.local_identifiers.append(name_node.text.decode("utf-8"))
        parameters_node = node.child_by_field_name("parameters")
        if parameters_node:
            for param in parameters_node.named_children:
                if param.type == "identifier":
                    if param.text.decode("utf-8") != "self" or not self.exclude_self:
                        hammock_block.local_variables.append(param.text.decode("utf-8"))
        current_parent = node.parent
        while current_parent:
            if current_parent.id in block_map and len(block_map[current_parent.id].block_full_qualifier):
                break
            current_parent = current_parent.parent
        hammock_block.block_full_qualifier = block_map[current_parent.id].block_full_qualifier + "." + name_node.text.decode("utf-8") if name_node else ""
        return hammock_block, []
    
    @parse_ts_node.register("return_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python return_statement"""
        print(f"[PYTHON] Dispatched to return_statement for node: {node.type}")
        print(f"[PYTHON] Return statement at line {node.start_point.row + 1}")
        # Find identifiers, variables, and strings in the expression subtree
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(node)
        current_parent = node.parent
        while current_parent:
            if current_parent.id in block_map and len(block_map[current_parent.id].block_full_qualifier):
                break
            current_parent = current_parent.parent
        hammock_block = block_map[current_parent.id]
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        return None, []
        
    @parse_ts_node.register("expression_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python expression_statement"""
        print(f"[PYTHON] Dispatched to parse_expression_statement for node: {node.type}")
        print(f"[PYTHON] Expression statement at line {node.start_point.row + 1}")
        # Only parse expression statements that are directly related to function definitions, class definitions, or module level
        if node.parent and (node.parent.type == "module" or node.parent.type == "block" and node.parent.parent and node.parent.parent.type in ["function_definition", "class_definition"]):
            hammock_block = self._base_block_builder(node)
            
            # Find identifiers, variables, and strings in the expression subtree
            identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(node)
            hammock_block.local_identifiers.extend(identifiers)
            hammock_block.local_variables.extend(variables)
            hammock_block.string_literals.extend(strings)
            return hammock_block, []
        else:
            print(f"[PYTHON] Skipping expression_statement not directly related to function definition: {node.type}")
            return None, []

    @parse_ts_node.register("if_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested!
        """Parse Python if_statement"""
        print(f"[PYTHON] Dispatched to parse_if_statement for node: {node.type}")
        print(f"[PYTHON] If statement at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        additional_blocks_list = []
        
        # part 1: parse the condition and consequence
        condition_node = node.child_by_field_name("condition")
        consequence_node = node.child_by_field_name("consequence")
        print(f"[PYTHON] IF clause at line {condition_node.start_point.row + 1}")
        if_consequence_child_block = self._base_block_builder(consequence_node)
        if_consequence_child_block.start_point = condition_node.start_point
        if_consequence_child_block.end_point = consequence_node.end_point
        if_consequence_child_block.block_type = "if_clause"
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(condition_node)
        if_consequence_child_block.local_identifiers.extend(identifiers)
        if_consequence_child_block.local_variables.extend(variables)
        if_consequence_child_block.string_literals.extend(strings)
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(consequence_node)
        if_consequence_child_block.local_identifiers.extend(identifiers)
        if_consequence_child_block.local_variables.extend(variables)
        if_consequence_child_block.string_literals.extend(strings)
        
        hammock_block.children.append(if_consequence_child_block)
        hammock_block.children_ids.append(if_consequence_child_block.block_id)
        if_consequence_child_block.parent = hammock_block
        assert if_consequence_child_block.block_id not in block_map, f"Block with id {if_consequence_child_block.block_id} already exists in block_map. This should not happen."
        block_map[if_consequence_child_block.block_id] = if_consequence_child_block
        additional_blocks_list.append(if_consequence_child_block)
        
        # part 2: parse the alternative(s)
        alternatives_nodes = node.children_by_field_name("alternative")
        for alternative_node in alternatives_nodes:
            if alternative_node.type == "elif_clause":
                print(f"[PYTHON] Elif clause at line {alternative_node.start_point.row + 1}")
                elif_condition_node = alternative_node.child_by_field_name("condition")
                elif_consequence_node = alternative_node.child_by_field_name("consequence")
                elif_consequence_child_block = self._base_block_builder(alternative_node)
                
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(elif_condition_node)
                elif_consequence_child_block.local_identifiers.extend(identifiers)
                elif_consequence_child_block.local_variables.extend(variables)
                elif_consequence_child_block.string_literals.extend(strings)
                
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(elif_consequence_node)
                elif_consequence_child_block.local_identifiers.extend(identifiers)
                elif_consequence_child_block.local_variables.extend(variables)
                elif_consequence_child_block.string_literals.extend(strings)
                
                hammock_block.children.append(elif_consequence_child_block)
                hammock_block.children_ids.append(elif_consequence_child_block.block_id)
                elif_consequence_child_block.parent = hammock_block
                assert elif_consequence_child_block.block_id not in block_map, f"Block with id {elif_consequence_child_block.block_id} already exists in block_map. This should not happen."
                block_map[elif_consequence_child_block.block_id] = elif_consequence_child_block
                additional_blocks_list.append(elif_consequence_child_block)
            elif alternative_node.type == "else_clause":
                print(f"[PYTHON] Else clause at line {alternative_node.start_point.row + 1}")
                else_consequence_child_block = self._base_block_builder(alternative_node)
                
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(alternative_node)
                else_consequence_child_block.local_identifiers.extend(identifiers)
                else_consequence_child_block.local_variables.extend(variables)
                else_consequence_child_block.string_literals.extend(strings)
                
                hammock_block.children.append(else_consequence_child_block)
                hammock_block.children_ids.append(else_consequence_child_block.block_id)
                else_consequence_child_block.parent = hammock_block
                assert else_consequence_child_block.block_id not in block_map, f"Block with id {else_consequence_child_block.block_id} already exists in block_map. This should not happen."
                block_map[else_consequence_child_block.block_id] = else_consequence_child_block
                additional_blocks_list.append(else_consequence_child_block)
        return hammock_block, additional_blocks_list

    @parse_ts_node.register("for_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python for_statement"""
        print(f"[PYTHON] Dispatched to parse_for_statement for node: {node.type}")
        print(f"[PYTHON] For loop at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        left_condition_node = node.child_by_field_name("left")
        right_condition_node = node.child_by_field_name("right")
        for_body_node = node.child_by_field_name("body")
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(left_condition_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(right_condition_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(for_body_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables) 
        hammock_block.string_literals.extend(strings)
        return hammock_block, []

    @parse_ts_node.register("while_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock: # Tested!
        """Parse Python while_statement"""
        print(f"[PYTHON] Dispatched to parse_while_statement for node: {node.type}")
        print(f"[PYTHON] While loop at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        condition_node = node.child_by_field_name("condition")
        while_body_node = node.child_by_field_name("body")
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(condition_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(while_body_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        return hammock_block, []

    @parse_ts_node.register("try_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested!
        """Parse Python try-except statement"""
        print(f"[PYTHON] Dispatched to parse_try_statement for node: {node.type}")
        print(f"[PYTHON] Try-except block at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        additional_blocks_list = []
        
        try_node = node.child_by_field_name("body")
        try_child_block = self._base_block_builder(try_node)
        try_child_block.start_point = hammock_block.start_point
        try_child_block.block_type = "try_clause"
        
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(try_node)
        try_child_block.local_identifiers.extend(identifiers)
        try_child_block.local_variables.extend(variables)
        try_child_block.string_literals.extend(strings)
        
        hammock_block.children_ids.append(try_child_block.block_id)
        assert try_child_block.block_id not in block_map, f"Block with id {try_child_block.block_id} already exists in block_map. This should not happen."
        block_map[try_child_block.block_id] = try_child_block
        hammock_block.children.append(try_child_block)
        try_child_block.parent = hammock_block
        additional_blocks_list.append(try_child_block)
        
        for child in node.named_children:
            if child.type == "except_clause":
                print(f"[PYTHON] Except clause at line {child.start_point.row + 1}")
                except_node = child 
                except_child_block = self._base_block_builder(except_node)
            
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(except_node)
                except_child_block.local_identifiers.extend(identifiers)
                except_child_block.local_variables.extend(variables)
                except_child_block.string_literals.extend(strings)
                
                assert except_child_block.block_id not in block_map, f"Block with id {except_child_block.block_id} already exists in block_map. This should not happen."
                block_map[except_child_block.block_id] = except_child_block
                hammock_block.children_ids.append(except_child_block.block_id)
                hammock_block.children.append(except_child_block)
                except_child_block.parent = hammock_block
                additional_blocks_list.append(except_child_block)
            elif child.type == "else_clause":
                print(f"[PYTHON] Else clause at line {child.start_point.row + 1}")
                else_node = child
                else_child_block = self._base_block_builder(else_node)
                
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(else_node)
                else_child_block.local_identifiers.extend(identifiers)
                else_child_block.local_variables.extend(variables)
                else_child_block.string_literals.extend(strings)
                
                assert else_child_block.block_id not in block_map, f"Block with id {else_child_block.block_id} already exists in block_map. This should not happen."
                block_map[else_child_block.block_id] = else_child_block
                hammock_block.children.append(else_child_block)
                hammock_block.children_ids.append(else_child_block.block_id)
                else_child_block.parent = hammock_block
                additional_blocks_list.append(else_child_block)
            elif child.type == "finally_clause":
                print(f"[PYTHON] Finally clause at line {child.start_point.row + 1}")
                finally_node = child
                finally_child_block = self._base_block_builder(finally_node)
            
                identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(finally_node)
                finally_child_block.local_identifiers.extend(identifiers)
                finally_child_block.local_variables.extend(variables)
                finally_child_block.string_literals.extend(strings)
                
                assert finally_child_block.block_id not in block_map, f"Block with id {finally_child_block.block_id} already exists in block_map. This should not happen."
                block_map[finally_child_block.block_id] = finally_child_block
                hammock_block.children.append(finally_child_block)
                hammock_block.children_ids.append(finally_child_block.block_id)
                finally_child_block.parent = hammock_block
                additional_blocks_list.append(finally_child_block)

        return hammock_block, additional_blocks_list

    @parse_ts_node.register("with_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested!
        """Parse Python with statement (context manager)"""
        print(f"[PYTHON] Dispatched to parse_with_statement for node: {node.type}")
        print(f"[PYTHON] With statement at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        return hammock_block, []
    
    @parse_ts_node.register("raise_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested!
        """Parse Python raise statement (context manager)"""
        print(f"[PYTHON] Dispatched to raise_statement for node: {node.type}")
        print(f"[PYTHON] Raise statement at line {node.start_point.row + 1}")
        raise NotImplementedError("Raise statement parsing is not implemented yet.")
        return None, []

    @parse_ts_node.register("match_statement")
    def parse_ts_node_impl(self, node: Node, block_map: Dict, source_file: str) -> TSHammockBlock:  # Tested!
        """Parse Python match_statement (pattern matching)"""
        print(f"[PYTHON] Dispatched to parse_match_statement for node: {node.type}")
        print(f"[PYTHON] Match statement at line {node.start_point.row + 1}")
        hammock_block = self._base_block_builder(node)
        additional_blocks_list = []
        
        subject_node = node.child_by_field_name("subject")
        identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(subject_node)
        hammock_block.local_identifiers.extend(identifiers)
        hammock_block.local_variables.extend(variables)
        hammock_block.string_literals.extend(strings)
        
        body_node = node.child_by_field_name("body")
        alternative_nodes = body_node.children_by_field_name("alternative") 
        for alternative_node in alternative_nodes:
            assert alternative_node.type == "case_clause", "Alternative node should be a case clause"            
            case_child_block = self._base_block_builder(alternative_node)
            
            identifiers, variables, strings = self._find_identifiers_locals_strings_in_subtree(alternative_node)
            case_child_block.local_identifiers.extend(identifiers)
            case_child_block.local_variables.extend(variables)
            case_child_block.string_literals.extend(strings)
            
            assert case_child_block.block_id not in block_map, f"Block with id {case_child_block.block_id} already exists in block_map. This should not happen."
            block_map[case_child_block.block_id] = case_child_block
            hammock_block.children_ids.append(case_child_block.block_id)
            hammock_block.children.append(case_child_block)
            case_child_block.parent = hammock_block
            additional_blocks_list.append(case_child_block)
        return hammock_block, additional_blocks_list

    def _base_block_builder(self, node: Node) -> TSHammockBlock:
        """Basic builder for TSHammockBlock"""
        block_id = node.id
        block_type = node.type
        start_point = node.start_point
        end_point = node.end_point
        children_ids = [child.id for child in node.named_children]
        hammock_block = TSHammockBlock(
            block_id=block_id,
            block_full_qualifier="",
            block_type=block_type,
            start_point=start_point,
            end_point=end_point,
            children_ids=children_ids,
        )
        return hammock_block

    def _find_identifiers_locals_strings_in_subtree(self, node: Node, exclude_nested_blocks: bool = True) -> tuple:
        """Walk the subtree with optional exclusion of nested statement blocks."""
        if not node:
            return [], [], []
        
        identifiers = []
        variables = []
        strings = []        
        stack = [node]
        visited = set()  

        # Get exclude types from registered types
        exclude_types = set()
        if exclude_nested_blocks:
            registered_types = self.parse_ts_node.get_registered_types()
            exclude_types = registered_types & self.supported_block_type

        while stack:
            current_node = stack.pop()
            if current_node.id in visited:
                continue
            visited.add(current_node.id)

            # Process current node based on its type and parent type
            if current_node.type == 'string':
                strings.append(current_node.text.decode("utf-8"))
                continue
            elif current_node.type == 'attribute':
                if current_node.parent and current_node.parent.type == 'call':
                    # This is likely a method call, treat as identifier
                    identifiers.append(current_node.text.decode("utf-8"))
                else:
                    # This is likely an attribute access, treat as variable
                    if current_node.text.decode("utf-8") != "self" or not self.exclude_self:
                        variables.append(current_node.text.decode("utf-8"))
                continue
            elif current_node.type == 'identifier':
                if self._is_function_or_class_name(current_node):
                    identifiers.append(current_node.text.decode("utf-8"))
                else:
                    variables.append(current_node.text.decode("utf-8"))
                continue

            # Add children to stack, but SKIP nested statement blocks
            for child in current_node.named_children:
                if child.id not in visited:
                    # Skip if this child is a statement block that will be processed separately
                    # BUT don't skip if it's the original node we're processing
                    if exclude_nested_blocks and child.type in exclude_types and child != node:
                        print(f"[PYTHON] Skipping nested {child.type} at line {child.start_point.row + 1}")
                        continue
                    stack.append(child)

        # Remove duplicates while preserving order
        identifiers = list(dict.fromkeys(identifiers))
        variables = list(dict.fromkeys(variables))
        strings = list(dict.fromkeys(strings))
        return identifiers, variables, strings

    def _is_function_or_class_name(self, node: Node) -> bool:
        """Check if the identifier is likely a function or class name based on its parent type."""
        parent = node.parent
        grandparent = parent.parent if parent else None
        if not parent:
            return False
        if parent.type == 'function_definition' or parent.type == 'class_definition':
            return True
        if parent.type == 'call':
            return True
        # This likely not needed because we process the attribute node in the _find_identifiers_locals_strings_in_subtree method
        # but we keep it here for safety
        if parent.type == 'attribute' and grandparent and grandparent.type == 'call':
            return True
        return False

    def _construct_caller_callee_relation_edges(self, block_map, pdg_map):
        list_of_caller_callee_edges = []
        for src_file in pdg_map:
            src_code_dir = self.src_file_to_dir_map[src_file]
            if self.cg_backend == "codeql":
                codeql_database = self.py_codeql_databases[src_code_dir]
                list_of_caller_callee_edges.extend(
                    self.cg_backend_utils.get_caller_callee_edges(codeql_database)
                )
            elif self.cg_backend == "scalpel":
                scalpel_callgraph = self.py_scalpel_callgraphs[src_code_dir]
                list_of_caller_callee_edges.extend(
                    self.cg_backend_utils.get_caller_callee_edges(scalpel_callgraph, src_code_dir, pdg_map[src_file])
                )
            else:
                raise ValueError(f"Unsupported cg_backend: {self.cg_backend}. Supported backends are: codeql.")
        for edge in list_of_caller_callee_edges:
            self._construct_caller_callee_relation_edges_helper(
                edge, block_map, pdg_map
            )
        print(f"[PYTHON] Constructed {len(list_of_caller_callee_edges)} caller-callee relation edges.")
        return

    def _construct_caller_callee_relation_edges_helper(self, edge, block_map, pdg_map):
        # Step 1: Extract caller and callee information from the edge
        caller_kind = edge[0].split(" ")[0]  # e.g., "Function", "Class", "Script"
        _ = edge[0].split(" ")[1]  # e.g., "main", "Module1", "main.py"
        caller_file_location = edge[1].split(":")[0]  # e.g., "/path/to/file.py"
        caller_file_line = int(edge[1].split(":")[1])
        callee_kind = edge[2].split(" ")[0]  # e.g., "Function", "Class"
        callee_name = edge[2].split(" ")[1]  # e.g., "Module1", "add"
        callee_file_location = edge[3].split(":")[0]  # e.g., "/path/to/file.py"
        callee_file_line = int(edge[3].split(":")[1])
        
        # Step 2: Find the corresponding blocks in the pdg_map 
        # We might be able to relax the following assertion if we can skip the missing caller and callee blocks
        assert caller_file_location in pdg_map, f"Caller file location {caller_file_location} not found in pdg_map."
        assert callee_file_location in pdg_map, f"Callee file location {callee_file_location} not found in pdg_map."
        caller_block = self._locate_hammock_block_from_file_line_and_type(
            pdg_map[caller_file_location], caller_file_line, caller_kind, True
        )
        callee_block = self._locate_hammock_block_from_file_line_and_type(
            pdg_map[callee_file_location], callee_file_line, callee_kind, False
        )
        
        # Step 3: Cross check informations between codeql results and hammock blocks
        if self.cg_backend == "codeql":
            assert callee_name in [fname.split(".")[-1] for fname in caller_block.local_identifiers], \
                f"Callee name {callee_name} not found in caller block {caller_block.block_id} identifiers: {caller_block.local_identifiers}"
            assert callee_name in [fname.split(".")[-1] for fname in callee_block.local_identifiers], \
                f"Callee name {callee_name} not found in callee block {callee_block.block_id} identifiers: {callee_block.local_identifiers}"
        elif self.cg_backend == "scalpel":
            assert callee_name.split(".")[-1] in [fname.split(".")[-1] for fname in caller_block.local_identifiers], \
                f"Callee name {callee_name} not found in caller block {caller_block.block_id} identifiers: {caller_block.local_identifiers}"
            assert callee_name.split(".")[-1] in [fname.split(".")[-1] for fname in callee_block.local_identifiers], \
                f"Callee name {callee_name} not found in callee block {callee_block.block_id} identifiers: {callee_block.local_identifiers}"
            # an additional check for scalpel because scalpel can resolve full qualifiers
            assert callee_name == callee_block.block_full_qualifier, \
                f"Callee name {callee_name} does not match callee block full qualifier {callee_block.block_full_qualifier} in block {callee_block.block_id}."
        else:
            raise ValueError(f"Unsupported cg_backend: {self.cg_backend}. Supported backends are: codeql, scalpel.")
        
        # Step 4: Create a relation and add it to the hammock blocks
        caller_relation = TSHBRelation(
            relation_type="function_call-callee",
            target_block_id=callee_block.block_id,
            functional_description="Function call to callee",
            target_block_type=callee_block.block_type,
            related_variables=[],  # This information should already be in the code snippet
            target_block_full_qualifier = callee_block.block_full_qualifier,
        ) 
        callee_relation = TSHBRelation(
            relation_type="function_call-caller",
            target_block_id=caller_block.block_id,
            functional_description="Function call from caller",
            target_block_type=caller_block.block_type,
            related_variables=[],  # This information should already be in the code snippet
            target_block_full_qualifier = caller_block.block_full_qualifier,
        )
        caller_block.relations.append(caller_relation)
        callee_block.relations.append(callee_relation)
        
        
    def _locate_hammock_block_from_file_line_and_type(self, pdg, line, kind, is_caller):
        if kind == "Function":
            block_type = "function_definition"
        elif kind == "Class":
            block_type = "class_definition"
        elif kind == "Script":
            block_type = "module"
        else:
            raise ValueError(f"Unsupported kind: {kind}. Supported callee kinds are Function, Class.")
        
        # Find the smallest enclosing hammock block of the given type at the specified line
        smallest_enclosing_block = None
        for hammock_block in pdg["hammock_blocks"]:
            if hammock_block.start_point.row <= line - 1 <= hammock_block.end_point.row:
                if hammock_block.block_type != block_type and not is_caller:
                    continue
                if smallest_enclosing_block is None:
                    smallest_enclosing_block = hammock_block
                if smallest_enclosing_block is not None and (hammock_block.start_point.row > smallest_enclosing_block.start_point.row or hammock_block.end_point.row < smallest_enclosing_block.end_point.row):
                    smallest_enclosing_block = hammock_block
                elif smallest_enclosing_block is not None and (hammock_block.start_point.row == smallest_enclosing_block.start_point.row and hammock_block.end_point.row == smallest_enclosing_block.end_point.row and hammock_block.parent and hammock_block.parent.block_id ==  smallest_enclosing_block.block_id):
                     smallest_enclosing_block = hammock_block
        return smallest_enclosing_block

    def _post_process_hammock_blocks(self, pdg, block_map):
        # 1. merge consecutive straightline blocks into a single hammock block
        # only merge block if they are straightline blocks and have the same parent
        basic_block_bookkeeping = {}
        for hammock_block in pdg["hammock_blocks"]:
            if hammock_block.block_type == "expression_statement":
                assert hammock_block.parent is not None, f"Hammock block {hammock_block.block_id} of type {hammock_block.block_type} has no parent. This should not happen."
                parent_block_id = hammock_block.parent.block_id
                if parent_block_id not in basic_block_bookkeeping:
                    basic_block_bookkeeping[parent_block_id] = []
                basic_block_bookkeeping[parent_block_id].append([hammock_block.block_id, hammock_block.start_point, hammock_block.end_point])
        # now we merge the consecutive straightline blocks into a single hammock block
        for parent_block_id, blocks in basic_block_bookkeeping.items():
            if len(blocks) < 2:
                continue
            # sort the blocks by start point
            blocks.sort(key=lambda x: x[1].row)
            merged_bookkeeping = []
            current_group = [[blocks[0][0], blocks[0][1], blocks[0][2]]]
            for i in range(1, len(blocks)):
                current_row_end = blocks[i-1][2].row
                next_row = blocks[i][1].row
                if next_row == current_row_end + 1:
                    current_group.append([blocks[i][0], blocks[i][1], blocks[i][2]])
                else:
                    merged_bookkeeping.append(current_group)
                    current_group = [[blocks[i][0], blocks[i][1], blocks[i][2]]]
            merged_bookkeeping.append(current_group)
            self._merge_consecutive_expression_statement_helper(merged_bookkeeping, pdg, block_map)
        
        # 2. ensure unqiue identifiers, strings, and variables
        for hammock_block in pdg["hammock_blocks"]:
            hammock_block.local_identifiers = list(set(hammock_block.local_identifiers))
            hammock_block.string_literals = list(set(hammock_block.string_literals))
            hammock_block.local_variables = list(set(hammock_block.local_variables))
        
        # 3. move callsites from if-statement to if-clause hammock blocks
        for hammock_block in pdg["hammock_blocks"]:
            if hammock_block.block_type == "if_statement":
                if_clause = None
                for child in hammock_block.children:
                    if child.block_type == "if_clause":
                        if if_clause is None:
                            if_clause = child
                        else:
                            raise RuntimeError(f"Multiple if_clause blocks found in if_statement {hammock_block.block_id}. This should not happen.")
                # move callsites from the if_statement to the if_clause blocks
                for callsite in hammock_block.local_callsites:
                    if_clause.local_callsites.append(callsite)
                hammock_block.local_callsites = []
    
    def _merge_consecutive_expression_statement_helper(self, merged_bookkeeping, pdg, block_map):
        for group in merged_bookkeeping:
            if len(group) < 2:
                continue
            else:
                removal_list = []
                anchor_block_id = group[0][0]
                anchor_block = block_map[anchor_block_id]
                for i in range(1, len(group)):
                    next_block_id = group[i][0]
                    next_block = block_map[next_block_id]
                    
                    # merge the next block into the anchor block
                    anchor_block.end_point = next_block.end_point
                    anchor_block.local_identifiers.extend(next_block.local_identifiers)
                    anchor_block.local_variables.extend(next_block.local_variables)
                    anchor_block.string_literals.extend(next_block.string_literals)
                    anchor_block.comments.extend(next_block.comments)
                    anchor_block.discard_children_ids.extend(next_block.discard_children_ids)
                    assert next_block.children_ids == [], f"Next block {next_block_id} has children, which should not happen for expression statements."
                    assert next_block.children_ids == [], f"Next block {next_block_id} has children_ids, which should not happen for expression statements."
                    anchor_block.relations.extend(next_block.relations)
                    anchor_block.imported_packages.extend(next_block.imported_packages)
                    anchor_block.local_callsites.extend(next_block.local_callsites)
                    
                    # add to removal list
                    removal_list.append(next_block_id)
                
                # remove the next blocks from the pdg and block_map
                for removal_id in removal_list:
                    # Use list comprehension to create a new list without the removed blocks
                    pdg["hammock_blocks"] = [block for block in pdg["hammock_blocks"] if block.block_id != removal_id]
                    del block_map[removal_id]
                    for block in pdg["hammock_blocks"]:
                        if removal_id in block.children_ids:
                            block.children_ids.remove(removal_id)
                        if removal_id in block.discard_children_ids:
                            block.discard_children_ids.remove(removal_id)
                        block.children = [child for child in block.children if child.block_id != removal_id]
