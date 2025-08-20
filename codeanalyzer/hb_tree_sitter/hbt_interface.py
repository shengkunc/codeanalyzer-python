import os
from typing import Optional
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock
from codeanalyzer.hb_tree_sitter.hbt_parser import PyHbtParser
from codeanalyzer.schema.py_schema import PyHammockBlock, PyHammockBlockRelation, PySymbol, PyCallsite, PyModule, PyVariableDeclaration, PyCallableParameter, PyClassAttribute
from pathlib import Path

class HammockBlockTreeBuilder:
    """
    Represents a Hammock Block tree for a Python module.
    This class is used to parse and analyze the structure of Hammock Blocks in Python code.
    """
    @staticmethod
    def parse(source: str, filename: str, project_base: str) -> Optional[TSHammockBlock]:
        """
        Parses the source code and returns a Hammock block tree instance.
        """
        hbt_parser = PyHbtParser(source, filename, project_base)
        ori_hbt_map = hbt_parser.get_full_pdg_map(filename)
        py_hbt_root, converted_hbt_map = HammockBlockTreeBuilder._convert_to_hbt(ori_hbt_map)
        return py_hbt_root, converted_hbt_map, ori_hbt_map 

    @staticmethod
    def _convert_to_hbt(ori_hbt_map: dict) -> Optional[TSHammockBlock]:
        """
        Converts the original Hammock Block map to a TSHammockBlock instance.
        """
        if not ori_hbt_map:
            return None, None
        
        converted_hbt_map = {"hammock_blocks": []}
        # Step 1: find the root block to the subtree in the map
        list_of_hbs = ori_hbt_map["hammock_blocks"]
        for hb in list_of_hbs:
            if hb.block_type == "module":
                assert hb.parent is None, "Root block should not have a parent."
                tshbt_root = hb
                break 

        # Step 2: traverse the TSHammockBlock subtree and build PyHammockBlock objects
        def traverse_hbt(node: TSHammockBlock) -> PyHammockBlock:
            """Recursively traverse TSHammockBlock tree and build PyHammockBlock objects."""
            children = []
            for child in node.children:
                children.append(traverse_hbt(child))
            py_hammock_block = (PyHammockBlock.builder()
                                .block_id(node.block_id)
                                .block_full_qualifier(node.block_full_qualifier)
                                .project_full_qualifier(node.project_full_qualifier)
                                .block_type(node.block_type)
                                .start_line(node.start_point.row + 1 if node.start_point else -1)
                                .end_line(node.end_point.row + 1 if node.end_point else -1)
                                .children(child.block_id for child in children)
                                .meta_data(node.meta_data)
                                .local_variables([])
                                .accessed_variables([])
                                .call_sites([])
                                .relations([])
                                .class_attributes([])
                                .func_parameters([])
                                .build())
            converted_hbt_map["hammock_blocks"].append(py_hammock_block)
            return py_hammock_block
        
        py_hbt_root = traverse_hbt(tshbt_root)
        
        # Step 3: fix parent relationships notice that 
        # parent of the root does not matter, only considering subtree
        def fix_parent_relationships(node: PyHammockBlock, parent: PyHammockBlock = None):
            """Recursively fix parent relationships in PyHammockBlock tree."""
            node.parent = parent.block_id if parent else None
            for child in node.children:
                for block in converted_hbt_map["hammock_blocks"]:
                    if block.block_id == child:
                        child_node = block
                        break
                fix_parent_relationships(child_node, node)
        fix_parent_relationships(py_hbt_root)
        return py_hbt_root, converted_hbt_map
    
    @staticmethod
    def build_hb_data_relations(converted_hbt_map):
        if converted_hbt_map is None:
            return
        for hb in converted_hbt_map["hammock_blocks"]:
            accessed_variables = hb.accessed_variables
            for variable in accessed_variables:
                # step 1: first search local block
                found = HammockBlockTreeBuilder._find_variables_in_local_block(variable, hb)
                if found:
                    # do nothing and continue, no relations needed for local scope variables
                    continue
                
                # step 2: if not found, search sibling blocks
                found_sibling_block, declaration = HammockBlockTreeBuilder._find_variables_in_sibling_blocks(variable, hb, converted_hbt_map)
                if found_sibling_block:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_sibling_block, variable, declaration)
                    
                    hb_relations = hb.relations
                    already_exist = False
                    for relation in hb_relations:
                        if relation.related_block_id == found_sibling_block.block_id and relation.related_variables[0].name == variable.name:
                            already_exist = True
                            break
                    if not already_exist:
                        # add relations only if not already exist
                        hb.relations.append(src_block_relation)
                        found_sibling_block.relations.append(tgt_block_relation)
                    else:
                        print(f"INFO: Relation already exists between {hb.block_id} and {found_sibling_block.block_id} for variable {variable.name}, skipping.")
                    continue
                
                # step 3: if still not found search parent block
                found_parent_block, declaration = HammockBlockTreeBuilder._find_variables_in_parent_blocks(variable, hb, converted_hbt_map)
                if found_parent_block:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_parent_block, variable, declaration)
                    
                    hb_relations = hb.relations
                    already_exist = False
                    for relation in hb_relations:
                        if relation.related_block_id == found_parent_block.block_id and relation.related_variables[0].name == variable.name:
                            already_exist = True
                            break
                    if not already_exist:
                        # add relations only if not already exist
                        hb.relations.append(src_block_relation)
                        found_parent_block.relations.append(tgt_block_relation)
                    else:
                        print(f"INFO: Relation already exists between {hb.block_id} and {found_parent_block.block_id} for variable {variable.name}, skipping.")
                    continue
                
                # step 4: or alternatively search all blocks in the Hammock Block map
                found_block, declaration = HammockBlockTreeBuilder._find_variables_in_all_blocks(variable, converted_hbt_map)
                if found_block:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_block, variable, declaration)
                    
                    hb_relations = hb.relations
                    already_exist = False
                    for relation in hb_relations:
                        if relation.related_block_id == found_block.block_id and relation.related_variables[0].name == variable.name:
                            already_exist = True
                            break
                    if not already_exist:
                        # add relations only if not already exist
                        hb.relations.append(src_block_relation)
                        found_block.relations.append(tgt_block_relation)
                    else:
                        print(f"INFO: Relation already exists between {hb.block_id} and {found_block.block_id} for variable {variable.name}, skipping.")
                    continue

    @staticmethod
    def _find_variables_in_local_block(variable, hb) -> bool:
        local_variabes = hb.local_variables
        for local_variable in local_variabes:
            if local_variable.name == variable.name:
                return True
        for class_attribute in hb.class_attributes:
            if class_attribute.name == variable.name:
                return True
        for func_parameter in hb.func_parameters:
            if func_parameter.name == variable.name:
                return True
        return False

    @staticmethod
    def _find_variables_in_sibling_blocks(variable, hb, converted_hbt_map) -> Optional[PyHammockBlock]:
        parent_id = hb.parent
        if parent_id is None:
            return None, None
        sibling_blocks = [
            block for block in converted_hbt_map["hammock_blocks"]
            if block.parent == parent_id and block.block_id != hb.block_id
        ]
        for sibling in sibling_blocks:
            local_variables = sibling.local_variables
            for local_variable in local_variables:
                if local_variable.name == variable.name:
                    return sibling, local_variable
            class_attributes = sibling.class_attributes
            for class_attribute in class_attributes:
                if class_attribute.name == variable.name:
                    return sibling, class_attribute
            # # variable declared in sibling cannot be function parameters
            # func_parameters = sibling.func_parameters
            # for func_parameter in func_parameters:  
            #     if func_parameter.name == variable.name:
            #         return sibling
        return None, None
    
    @staticmethod
    def _find_variables_in_parent_blocks(variable, hb, converted_hbt_map) -> Optional[PyHammockBlock]:
        current_parent_id = hb.parent
        if current_parent_id is None:
            return None, None
        all_parents = []
        while current_parent_id is not None:
            for block in converted_hbt_map["hammock_blocks"]:
                if block.block_id == current_parent_id:
                    all_parents.append(block)
                    current_parent_id = block.parent
        for block in all_parents:
            local_variables = block.local_variables
            for local_variable in local_variables:
                if local_variable.name == variable.name:
                    return block, local_variable
            class_attributes = block.class_attributes
            for class_attribute in class_attributes:
                if class_attribute.name == variable.name:
                    return block, class_attribute
            func_parameters = block.func_parameters
            for func_parameter in func_parameters:
                if func_parameter.name == variable.name:
                    return block, func_parameter
        return None, None
    
    @staticmethod
    def _find_variables_in_all_blocks(variable, converted_hbt_map) -> Optional[PyHammockBlock]:
        for block in converted_hbt_map["hammock_blocks"]:
            local_variables = block.local_variables
            for local_variable in local_variables:
                if local_variable.name == variable.name:
                    return block, local_variable
            class_attributes = block.class_attributes
            for class_attribute in class_attributes:
                if class_attribute.name == variable.name:
                    return block, class_attribute
            func_parameters = block.func_parameters
            for func_parameter in func_parameters:
                if func_parameter.name == variable.name:
                    return block, func_parameter
        return None, None

    @staticmethod
    def _build_data_relation_helper(src_block: PyHammockBlock, tgt_block: PyHammockBlock, variable: PySymbol, declaration: PyVariableDeclaration|PyCallableParameter|PyClassAttribute) -> PyHammockBlockRelation:
        if tgt_block.block_type != "import_statement" and tgt_block.block_type != "import_from_statement":
            src_block_relation = (PyHammockBlockRelation.builder()
                                    .relation_type("data_relation: variable_declaration")
                                    .related_block_id(tgt_block.block_id)
                                    .related_block_full_qualifier(tgt_block.block_full_qualifier)
                                    .related_project_full_qualifier(tgt_block.project_full_qualifier)
                                    .related_block_type(tgt_block.block_type)
                                    .related_variables((variable, declaration))
                                    .build())
        else:
            src_block_relation = (PyHammockBlockRelation.builder()
                                    .relation_type("data_relation: variable_imported")
                                    .related_block_id(tgt_block.block_id)
                                    .related_block_full_qualifier(tgt_block.block_full_qualifier)
                                    .related_project_full_qualifier(tgt_block.project_full_qualifier)
                                    .related_block_type(tgt_block.block_type)
                                    .related_variables((variable, declaration))
                                    .build())
        tgt_block_relation = (PyHammockBlockRelation.builder()
                                .relation_type("data_relation: variable_accessed")
                                .related_block_id(src_block.block_id)
                                .related_block_full_qualifier(src_block.block_full_qualifier)
                                .related_project_full_qualifier(src_block.project_full_qualifier)
                                .related_block_type(src_block.block_type)
                                .related_variables((variable, declaration))
                                .build())
        return src_block_relation, tgt_block_relation
    
    @staticmethod
    def build_caller_callee_relations(symbol_table: dict[Path, PyModule], project_dir: str):
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
                        if callee_block is not None:
                            HammockBlockTreeBuilder._build_caller_callee_relation_helper(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue
                    
                    # case 2: if the callee_signature is not null and match the method name, but the 
                    # receiver type and expression are both null, module level function call
                    elif callee_signature is not None and call_site.receiver_type is None and call_site.receiver_expr is None and method_name == callee_signature.split(".")[-1]:
                        callee_path, _ = HammockBlockTreeBuilder._resolve_hb_callee_path(callee_signature, list(symbol_table.keys()), project_dir)
                        callee_py_module = symbol_table.get(callee_path)
                        relevant_blocks = [hb for hb in callee_py_module.module_hammock_blocks]
                        for temp_block in relevant_blocks:
                            if len(temp_block.project_full_qualifier) and temp_block.project_full_qualifier == callee_signature: 
                                callee_block = temp_block
                                break
                        if callee_block is not None:
                            HammockBlockTreeBuilder._build_caller_callee_relation_helper(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue     
                    
                    # case 3:  if the callee_signature is not null and does not match the method name, but the
                    # receiver type or receiver expression is not null, class level method call
                    elif callee_signature is not None and (call_site.receiver_type is not None or call_site.receiver_expr is not None):
                        real_callee_signature = callee_signature + "." + method_name
                        callee_path, _ = HammockBlockTreeBuilder._resolve_hb_callee_path(real_callee_signature, list(symbol_table.keys()), project_dir)
                        callee_py_module = symbol_table.get(callee_path)
                        relevant_blocks = [hb for hb in callee_py_module.module_hammock_blocks]
                        for temp_block in relevant_blocks:
                            if len(temp_block.project_full_qualifier) and temp_block.project_full_qualifier == real_callee_signature: 
                                callee_block = temp_block
                                break
                        if callee_block is not None:
                            HammockBlockTreeBuilder._build_caller_callee_relation_helper(
                                block, 
                                call_site,
                                callee_block
                            )
                            continue
                    else:
                        print(f"WARN: Unexpected call site: {call_site}, investigate")
                        continue     
        return
    
    @ staticmethod
    def _build_caller_callee_relation_helper(caller_block: PyHammockBlock, call_site: PyCallsite, callee_block: PyHammockBlock) -> None:
        caller_block_relation = (PyHammockBlockRelation.builder()
                                .relation_type("caller_callee_relation: function_invocation_to_callee")
                                .related_block_id(callee_block.block_id)
                                .related_block_full_qualifier(callee_block.block_full_qualifier)
                                .related_project_full_qualifier(callee_block.project_full_qualifier)
                                .related_block_type(callee_block.block_type)
                                .related_call_site(call_site)
                                .build())
        
        callee_block_relation = (PyHammockBlockRelation.builder()
                                .relation_type("caller_callee_relation: function_invocation_from_caller")
                                .related_block_id(caller_block.block_id)
                                .related_block_full_qualifier(caller_block.block_full_qualifier)
                                .related_project_full_qualifier(caller_block.project_full_qualifier)
                                .related_block_type(caller_block.block_type)
                                .related_call_site(call_site)
                                .build())
        
        caller_block.relations.append(caller_block_relation)
        callee_block.relations.append(callee_block_relation)
    
    @staticmethod
    def _resolve_hb_callee_path(callee_signature: str, file_paths: str, project_dir: str) -> str:
        relative_paths = [file_path.replace(str(project_dir) + "/", "") for file_path in file_paths]
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
                rel_callee_path = relative_paths[idx]
                callee_module = module
        return os.path.join(project_dir, rel_callee_path), callee_module