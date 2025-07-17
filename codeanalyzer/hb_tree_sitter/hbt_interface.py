from typing import Optional
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock
from codeanalyzer.hb_tree_sitter.hbt_parser import PyHbtParser
from codeanalyzer.schema.py_schema import PyHammockBlock, PyHammockBlockRelation, PySymbol

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
                found_sibling_block = HammockBlockTreeBuilder._find_variables_in_sibling_blocks(variable, hb, converted_hbt_map)
                if found_sibling_block:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_sibling_block, variable)
                    
                    hb.relations.append(src_block_relation)
                    found_sibling_block.relations.append(tgt_block_relation)
                    continue
                
                # step 3: if still not found search parent block
                found_parent_block = HammockBlockTreeBuilder._find_variables_in_parent_block(variable, hb, converted_hbt_map)
                if found:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_parent_block, variable)
                    
                    hb.relations.append(src_block_relation)
                    found_parent_block.relations.append(tgt_block_relation)
                    continue
                
                # step 4: or alternatively search all blocks in the Hammock Block map
                found_block = HammockBlockTreeBuilder._find_variables_in_all_blocks(variable, converted_hbt_map)
                if found:
                    src_block_relation, tgt_block_relation = HammockBlockTreeBuilder._build_data_relation_helper(hb, found_block, variable)
                    
                    hb.relations.append(src_block_relation)
                    found_parent_block.relations.append(tgt_block_relation)
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
            return None
        sibling_blocks = [
            block for block in converted_hbt_map["hammock_blocks"]
            if block.parent == parent_id and block.block_id != hb.block_id
        ]
        for sibling in sibling_blocks:
            local_variables = sibling.local_variables
            for local_variable in local_variables:
                if local_variable.name == variable.name:
                    return sibling
            class_attributes = sibling.class_attributes
            for class_attribute in class_attributes:
                if class_attribute.name == variable.name:
                    return sibling
            func_parameters = sibling.func_parameters
            for func_parameter in func_parameters:  
                if func_parameter.name == variable.name:
                    return sibling
        return None
    
    @staticmethod
    def _find_variables_in_parent_block(variable, hb, converted_hbt_map) -> Optional[PyHammockBlock]:
        parent_id = hb.parent
        if parent_id is None:
            return None
        for block in converted_hbt_map["hammock_blocks"]:
            if block.block_id == parent_id:
                local_variables = block.local_variables
                for local_variable in local_variables:
                    if local_variable.name == variable.name:
                        return block
                class_attributes = block.class_attributes
                for class_attribute in class_attributes:
                    if class_attribute.name == variable.name:
                        return block
                func_parameters = block.func_parameters
                for func_parameter in func_parameters:
                    if func_parameter.name == variable.name:
                        return block
        return None
    
    @staticmethod
    def _find_variables_in_all_blocks(variable, converted_hbt_map) -> Optional[PyHammockBlock]:
        for block in converted_hbt_map["hammock_blocks"]:
            local_variables = block.local_variables
            for local_variable in local_variables:
                if local_variable.name == variable.name:
                    return block
            class_attributes = block.class_attributes
            for class_attribute in class_attributes:
                if class_attribute.name == variable.name:
                    return block
            func_parameters = block.func_parameters
            for func_parameter in func_parameters:
                if func_parameter.name == variable.name:
                    return block
        return None

    @staticmethod
    def _build_data_relation_helper(src_block: PyHammockBlock, tgt_block: PyHammockBlock, variable: PySymbol) -> PyHammockBlockRelation:
        src_block_relation = (PyHammockBlockRelation.builder()
                                            .relation_type("variable_declaration")
                                            .related_block_id(tgt_block.block_id)
                                            .related_block_full_qualifier(tgt_block.block_full_qualifier)
                                            .related_block_type(tgt_block.block_type)
                                            .related_variables(variable)
                                            .build())
        tgt_block_relation = (PyHammockBlockRelation.builder()
                                .relation_type("variable_accessed")
                                .related_block_id(src_block.block_id)
                                .related_block_full_qualifier(src_block.block_full_qualifier)
                                .related_block_type(src_block.block_type)
                                .related_variables(variable)
                                .build())
        return src_block_relation, tgt_block_relation