
import weakref
from spyvm import model, version, constants
from spyvm.version import elidable_for_version
from rpython.rlib import objectmodel, jit
from rpython.rlib.objectmodel import import_from_mixin
import rstrategies as rstrat

class AbstractShadow(object):
    """A shadow is an optional extra bit of information that
    can be attached at run-time to any Smalltalk object.
    """
    _attrs_ = ['_w_self', 'space']
    _immutable_fields_ = ['space']
    provides_getname = False
    repr_classname = "AbstractShadow"

    def __init__(self, space, w_self, size):
        self.space = space
        assert w_self is None or isinstance(w_self, model.W_PointersObject)
        self._w_self = w_self
    def w_self(self):
        return self._w_self
    def getname(self):
        raise NotImplementedError("Abstract class")
    def __repr__(self):
        if self.provides_getname:
            return "<%s %s>" % (self.repr_classname, self.getname())
        else:
            return "<%s>" % self.repr_classname

    def fetch(self, n0):
        raise NotImplementedError("Abstract class")
    def store(self, n0, w_value):
        raise NotImplementedError("Abstract class")
    def size(self):
        raise NotImplementedError("Abstract class")

    # This will invoke an appropriate copy_from_* method.
    # Overwriting this allows optimized transitions between certain storage types.
    def copy_into(self, other_shadow):
        other_shadow.copy_from(self)
    
    def attach_shadow(self): pass

    def copy_field_from(self, n0, other_shadow):
        self.store(n0, other_shadow.fetch(n0))

    def copy_from(self, other_shadow):
        assert self.size() == other_shadow.size()
        for i in range(self.size()):
            self.copy_field_from(i, other_shadow)
    
    def copy_from_AllNil(self, all_nil_storage):
        self.copy_from(all_nil_storage)
    def copy_from_SmallIntegerOrNil(self, small_int_storage):
        self.copy_from(small_int_storage)
    def copy_from_FloatOrNil(self, float_storage):
        self.copy_from(float_storage)

# ========== Storage classes implementing storage strategies ==========

class AbstractStorageShadow(AbstractShadow):
    repr_classname = "AbstractStorageShadow"
    import_from_mixin(rstrat.SafeIndexingMixin)
    
    def __init__(self, space, w_self, size):
        AbstractShadow.__init__(self, space, w_self, size)
        self.init_strategy(size)
    
    def strategy_factory(self):
        return self.space.strategy_factory
    
    def copy_from_AllNilStrategy(self, all_nil_storage):
        pass # Fields already initialized to nil

class AllNilStorageShadow(AbstractStorageShadow):
    repr_classname = "AllNilStorageShadow"
    import_from_mixin(rstrat.SingleValueStrategy)
    def value(self): return self.space.w_nil

class SmallIntegerOrNilStorageShadow(AbstractStorageShadow):
    repr_classname = "SmallIntegerOrNilStorageShadow"
    import_from_mixin(rstrat.TaggingStrategy)
    contained_type = model.W_SmallInteger
    def wrap(self, val): return self.space.wrap_int(val)
    def unwrap(self, w_val): return self.space.unwrap_int(w_val)
    def default_value(self): return self.space.w_nil
    def wrapped_tagged_value(self): return self.space.w_nil
    def unwrapped_tagged_value(self): return constants.MAXINT

class FloatOrNilStorageShadow(AbstractStorageShadow):
    repr_classname = "FloatOrNilStorageShadow"
    import_from_mixin(rstrat.TaggingStrategy)
    contained_type = model.W_Float
    def wrap(self, val): return self.space.wrap_float(val)
    def unwrap(self, w_val): return self.space.unwrap_float(w_val)
    def default_value(self): return self.space.w_nil
    def wrapped_tagged_value(self): return self.space.w_nil
    def unwrapped_tagged_value(self): import sys; return sys.float_info.max

class ListStorageShadow(AbstractStorageShadow):
    repr_classname = "ListStorageShadow"
    import_from_mixin(rstrat.GenericStrategy)
    def default_value(self): return self.space.w_nil

class WeakListStorageShadow(AbstractStorageShadow):
    repr_classname = "WeakListStorageShadow"
    import_from_mixin(rstrat.WeakGenericStrategy)
    def default_value(self): return self.space.w_nil

class StrategyFactory(rstrat.StrategyFactory):
    _immutable_fields_ = ["space", "no_specialized_storage?"]
    def __init__(self, space):
        from spyvm import objspace
        self.space = space
        self.no_specialized_storage = objspace.ConstantFlag()
        rstrat.StrategyFactory.__init__(self, AbstractStorageShadow, {
            AllNilStorageShadow: [SmallIntegerOrNilStorageShadow,
                                    FloatOrNilStorageShadow,
                                    ListStorageShadow],
            SmallIntegerOrNilStorageShadow: [ListStorageShadow],
            FloatOrNilStorageShadow: [ListStorageShadow],
        })
    
    def strategy_type_for(self, objects, weak=False):
        if weak:
            WeakListStorageShadow
        if self.no_specialized_storage.is_set():
            return ListStorageShadow
        return rstrat.StrategyFactory.strategy_type_for(self, objects)
    
    def empty_storage(self, w_self, size, weak=False):
        if weak:
            return WeakListStorageShadow(self.space, w_self, size)
        if self.no_specialized_storage.is_set():
            return ListStorageShadow(self.space, w_self, size)
        return AllNilStorageShadow(self.space, w_self, size)
    
    def instantiate_and_switch(self, old_strategy, size, strategy_class):
        w_self = old_strategy.w_self()
        instance = strategy_class(self.space, w_self, size)
        w_self.store_shadow(instance)
        instance.attach_shadow()
        return instance
    
    def instantiate_empty(self, strategy_type):
        return strategy_type(self.space, None, 0)

# ========== Other storage classes, non-strategies ==========

class AbstractRedirectingShadow(AbstractShadow):
    _attrs_ = ['_w_self_size']
    repr_classname = "AbstractRedirectingShadow"

    def __init__(self, space, w_self, size):
        if w_self is not None:
            self._w_self_size = w_self.size()
        else:
            self._w_self_size = size
        AbstractShadow.__init__(self, space, w_self, self._w_self_size)

    def size(self):
        return self._w_self_size

class AbstractCachingShadow(ListStorageShadow):
    _immutable_fields_ = ['version?']
    _attrs_ = ['version']
    repr_classname = "AbstractCachingShadow"
    import_from_mixin(version.VersionMixin)
    version = None

    def __init__(self, space, w_self, size):
        ListStorageShadow.__init__(self, space, w_self, size)
        self.changed()

class CachedObjectShadow(AbstractCachingShadow):
    repr_classname = "CachedObjectShadow"

    @elidable_for_version
    def fetch(self, n0):
        return AbstractCachingShadow.fetch(self, n0)

    def store(self, n0, w_value):
        AbstractCachingShadow.store(self, n0, w_value)
        self.changed()

class ObserveeShadow(ListStorageShadow):
    _attrs_ = ['dependent']
    repr_classname = "ObserveeShadow"
    def __init__(self, space, w_self, size):
        ListStorageShadow.__init__(self, space, w_self, size)
        self.dependent = None

    def store(self, n0, w_value):
        ListStorageShadow.store(self, n0, w_value)
        if self.dependent:
            self.dependent.update()

    def notify(self, dependent):
        if self.dependent is not None and dependent is not self.dependent:
            raise RuntimeError('Meant to be observed by only one value, so far')
        self.dependent = dependent