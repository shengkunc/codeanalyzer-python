from typing import Optional
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock
from codeanalyzer.hb_tree_sitter.hbt_parser import PyHbtParser
from codeanalyzer.schema.py_schema import PyHammockBlock

class HammockBlockTree:
    """
    Represents a Hammock Block tree for a Python module.
    This class is used to parse and analyze the structure of Hammock Blocks in Python code.
    """
    @staticmethod
    def parse(source: str, filename: str) -> Optional[TSHammockBlock]:
        """
        Parses the source code and returns a HammockBlockTree instance.
        """
        hbt_parser = PyHbtParser(source, filename)
        ori_hbt_map = hbt_parser.get_full_pdg_map(filename)
        py_hbt_root, converted_hbt_map = HammockBlockTree._convert_to_hbt(ori_hbt_map)
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
