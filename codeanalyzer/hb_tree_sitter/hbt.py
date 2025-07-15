from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock
from codeanalyzer.hb_tree_sitter.hbt_parser import PyHbtParser

class HammockBlockTree:
    """
    Represents a Hammock Block tree for a Python module.
    This class is used to parse and analyze the structure of Hammock Blocks in Python code.
    """
    @staticmethod
    def parse(source: str, filename: str) -> TSHammockBlock | None:
        """
        Parses the source code and returns a HammockBlockTree instance.
        """
        hbt_parser = PyHbtParser(source, filename)
        hbt_root = hbt_parser.get_full_hbt_root(filename)
        return hbt_root