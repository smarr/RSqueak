
import weakref
from rpython.rlib import jit

class StrategyFactory(object):
    _immutable_fields_ = ["strategies[*]"]
    
    def __init__(self, strategy_root_class, transitions):
        self.strategies = []
        self.root_class = strategy_root_class
        
        for strategy_class, generalized in transitions.items():
            self.strategies.append(strategy_class)
            strategy_class._strategy_instance = self.instantiate_empty(strategy_class)
            
            # Patch root class: Add default handler for visitor
            def copy_from_OTHER(self, other):
                self.copy_from(other)
            funcname = "copy_from_" + strategy_class.__name__
            copy_from_OTHER.func_name = funcname
            setattr(self.root_class, funcname, copy_from_OTHER)
            
            # Patch strategy class: Add polymorphic visitor function
            def initiate_copy_into(self, other):
                getattr(other, funcname)(self)
            strategy_class.initiate_copy_into = initiate_copy_into
            
            self.create_transition(strategy_class, generalized)
    
    # Instantiate new_strategy_type with size, replace old_strategy with it,
    # and return the new instance
    def instantiate_and_switch(self, old_strategy, size, new_strategy_type):
        raise NotImplementedError("Abstract method")
    
    # Return a functional but empty instance of strategy_type
    def instantiate_empty(self, strategy_type):
        raise NotImplementedError("Abstract method")
    
    def switch_strategy(self, old_strategy, new_strategy_type):
        new_instance = self.instantiate_and_switch(old_strategy, old_strategy.size(), new_strategy_type)
        old_strategy.initiate_copy_into(new_instance)
        return new_instance
    
    @jit.unroll_safe
    def strategy_type_for(self, objects):
        specialized_strategies = len(self.strategies)
        can_handle = [True] * specialized_strategies
        for obj in objects:
            if specialized_strategies <= 1:
                break
            for i, strategy in enumerate(self.strategies):
                if can_handle[i] and not strategy._strategy_instance.check_can_handle(obj):
                    can_handle[i] = False
                    specialized_strategies -= 1
        for i, strategy_type in enumerate(self.strategies):
            if can_handle[i]:
                return strategy_type
    
    def cannot_handle_value(self, old_strategy, index0, value):
        strategy_type = old_strategy.generalized_strategy_for(value)
        new_instance = self.switch_strategy(old_strategy, strategy_type)
        new_instance.store(index0, value)
    
    def _freeze_(self):
        # Instance will be frozen at compile time, making accesses constant.
        return True
    
    def create_transition(self, strategy_class, generalized):
        # Patch strategy class: Add generalized_strategy_for
        def generalized_strategy_for(self, value):
            for strategy in generalized:
                if strategy._strategy_instance.check_can_handle(value):
                    return strategy
            raise Exception("Could not find generalized strategy for %s coming from %s" % (value, self))
        strategy_class.generalized_strategy_for = generalized_strategy_for
    
class AbstractStrategy(object):
    # == Required:
    # strategy_factory(self) - Access to StorageFactory
    # __init__(...) - Constructor should invoke the provided init_strategy(self, size) method
    
    def init_strategy(self, initial_size):
        pass
    
    def store(self, index0, value):
        raise NotImplementedError("Abstract method")
    
    def fetch(self, index0):
        raise NotImplementedError("Abstract method")
    
    def size(self):
        raise NotImplementedError("Abstract method")
        
    def check_can_handle(self, value):
        raise NotImplementedError("Abstract method")
    
    def cannot_handle_value(self, index0, value):
        self.strategy_factory().cannot_handle_value(self, index0, value)
    
    def initiate_copy_into(self, other):
        other.copy_from(self)
    
    def copy_from(self, other):
        assert self.size() == other.size()
        for i in range(self.size()):
            self.copy_field_from(i, other)
    
    def copy_field_from(self, n0, other):
        self.store(n0, other.fetch(n0))
    
# ============== Special Strategies with no storage array ==============

class EmptyStrategy(AbstractStrategy):
    # == Required:
    # See AbstractStrategy
    
    def fetch(self, index0):
        raise IndexError
    def store(self, index0, value):
        self.cannot_handle_value(index0, value)
    def size(self):
        return 0
    def check_can_handle(self, value):
        return False
    
class SingleValueStrategy(AbstractStrategy):
    _immutable_fields_ = ["_size", "val"]
    # == Required:
    # See AbstractStrategy
    # check_index_*(...) - use mixin SafeIndexingMixin or UnsafeIndexingMixin
    # value(self) - the single value contained in this strategy
    
    def init_strategy(self, initial_size):
        self._size = initial_size
        self.val = self.value()
    def fetch(self, index0):
        self.check_index_fetch(index0)
        return self.val
    def store(self, index0, value):
        self.check_index_store(index0)
        if self.val is value:
            return
        self.cannot_handle_value(index0, value)
    def size(self):
        return self._size
    def check_can_handle(self, value):
        return value is self.val
    
# ============== Basic strategies with storage ==============

class StrategyWithStorage(AbstractStrategy):
    _immutable_fields_ = ["storage"]
    # == Required:
    # See AbstractStrategy
    # check_index_*(...) - use mixin SafeIndexingMixin, UnsafeIndexingMixin or VariableSizeMixin
    # default_value(self) - The value to be initially contained in this strategy
    
    def init_strategy(self, initial_size):
        self.init_StrategyWithStorage(initial_size)
    
    def init_StrategyWithStorage(self, initial_size):
        default = self._unwrap(self.default_value())
        self.storage = [default] * initial_size
    
    def store(self, index0, wrapped_value):
        self.check_index_store(index0)
        if self.check_can_handle(wrapped_value):
            unwrapped = self._unwrap(wrapped_value)
            self.storage[index0] = unwrapped
        else:
            self.cannot_handle_value(index0, wrapped_value)
    
    def fetch(self, index0):
        self.check_index_fetch(index0)
        unwrapped = self.storage[index0]
        return self._wrap(unwrapped)
    
    def _wrap(self, value):
        raise NotImplementedError("Abstract method")
    
    def _unwrap(self, value):
        raise NotImplementedError("Abstract method")
    
    def size(self):
        return len(self.storage)
    
class GenericStrategy(StrategyWithStorage):
    # == Required:
    # See StrategyWithStorage
    
    def _wrap(self, value):
        return value
    def _unwrap(self, value):
        return value
    def check_can_handle(self, wrapped_value):
        return True
    
class WeakGenericStrategy(StrategyWithStorage):
    # == Required:
    # See StrategyWithStorage
    
    def _wrap(self, value):
        return value() or self.default_value()
    def _unwrap(self, value):
        assert value is not None
        return weakref.ref(value)
    def check_can_handle(self, wrapped_value):
        return True
    
# ============== Mixins for StrategyWithStorage ==============

class SafeIndexingMixin(object):
    def check_index_store(self, index0):
        self.check_index(index0)
    def check_index_fetch(self, index0):
        self.check_index(index0)
    def check_index(self, index0):
        if index0 < 0 or index0 >= self.size():
            raise IndexError

class UnsafeIndexingMixin(object):
    def check_index_store(self, index0):
        pass
    def check_index_fetch(self, index0):
        pass

class VariableSizeMixin(object):
    # This can be used with StrategyWithStorage
    # to add functionality for resizing the storage.
    # Can be combined with either *IndexingMixin or *AutoresizeMixin
    
    @jit.unroll_safe
    def grow(self, by):
        if by <= 0:
            raise ValueError
        for _ in range(by):
            self.storage.append(self.default_value())
    
    @jit.unroll_safe
    def shrink(self, by):
        if by <= 0:
            raise ValueError
        if by > self.size():
            raise ValueError
        for _ in range(by):
            self.storage.pop()
    
class SafeAutoresizeMixin(object):
    def check_index_fetch(self, index0):
        if index0 < 0 or index0 > self.size():
            raise IndexError
    def check_index_store(self, index0):
        size = self.size()
        if index0 < 0:
            raise IndexError
        if index0 >= size:
            self.grow(index0 - size + 1)
    
class UnsafeAutoresizeMixin(object):
    def check_index_fetch(self, index0):
        pass
    def check_index_store(self, index0):
        size = self.size()
        if index0 >= size:
            self.grow(index0 - size)
    
# ============== Specialized Storage Strategies ==============

class SpecializedStrategy(StrategyWithStorage):
    # == Required:
    # See StrategyWithStorage
    # wrap(self, value) - Return a boxed object for the primitive value
    # unwrap(self, value) - Return the unboxed primitive value of value
    
    def _unwrap(self, value):
        return self.unwrap(value)
    def _wrap(self, value):
        return self.wrap(value)
    
class SingleTypeStrategy(SpecializedStrategy):
    # == Required Functions:
    # See SpecializedStrategy
    # contained_type - The wrapped type that can be stored in this strategy
    
    def check_can_handle(self, value):
        return isinstance(value, self.contained_type)
    
class TaggingStrategy(SingleTypeStrategy):
    """This strategy uses a special tag value to represent a single additional object."""
    # == Required:
    # See SingleTypeStrategy
    # wrapped_tagged_value(self) - The tagged object
    # unwrapped_tagged_value(self) - The unwrapped tag value representing the tagged object
    
    def init_strategy(self, initial_size):
        self.tag = self.unwrapped_tagged_value()
        self.w_tag = self.wrapped_tagged_value()
        self.init_StrategyWithStorage(initial_size)
    
    def check_can_handle(self, value):
        return value is self.w_tag or \
                (isinstance(value, self.contained_type) and \
                self.unwrap(value) != self.tag)
    
    def _unwrap(self, value):
        if value is self.w_tag:
            return self.tag
        return self.unwrap(value)
    
    def _wrap(self, value):
        if value == self.tag:
            return self.w_tag
        return self.wrap(value)