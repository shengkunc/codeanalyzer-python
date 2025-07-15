from typing import NewType, Dict, Callable
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock
from tree_sitter import Language, Parser, Tree, Node, Point
from functools import wraps


class NodeTypeDispatcher:
    def __init__(self):
        self.registry: Dict[str, Callable] = {}
        self.original_wrapper = None  # Will be set by ts_node_overload
    
    def register(self, node_type: str):
        def decorator(func: Callable):
            self.registry[node_type] = func
            # Return the original wrapper so subsequent @register calls work
            return self.original_wrapper if self.original_wrapper else func
        return decorator
    
    def get_registered_types(self) -> set:
        """Return a set of all registered node types"""
        return set(self.registry.keys())
    
    def __call__(self, instance, node: Node, block_map: Dict = None, source_file: str = None) -> TSHammockBlock:
        if not node:
            return None
        
        parser_func = self.registry.get(node.type)
        if parser_func:
            return parser_func(instance, node, block_map, source_file)
        else:
            default_parser = getattr(instance, '_parse_default', None)
            if (default_parser):
                return default_parser(node, block_map, source_file)
            raise NotImplementedError(f"No parser registered for node type: {node.type}")


def ts_node_overload(func):
    dispatcher = NodeTypeDispatcher()
    
    @wraps(func)
    def wrapper(self, node: Node, block_map: Dict = None, source_file: str = None) -> TSHammockBlock:
        return dispatcher(self, node, block_map, source_file)
    
    # Store reference to wrapper in dispatcher so register can return it
    dispatcher.original_wrapper = wrapper
    
    wrapper.register = dispatcher.register
    wrapper.registry = dispatcher.registry
    wrapper.get_registered_types = dispatcher.get_registered_types
    
    return wrapper