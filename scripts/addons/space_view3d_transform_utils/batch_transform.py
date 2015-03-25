#  ***** BEGIN GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#  ***** END GPL LICENSE BLOCK *****

#============================================================================#

import bpy
import bmesh

import math
import time
import json
import string

import mathutils.geometry
from mathutils import Color, Vector, Euler, Quaternion, Matrix

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_math import lerp, matrix_LRS, matrix_compose, matrix_decompose, matrix_inverted_safe, orthogonal_XYZ, orthogonal
from {0}dairin0d.utils_python import setattr_cmp, setitem_cmp, AttributeHolder, attrs_to_dict, dict_to_attrs, bools_to_int, binary_search
from {0}dairin0d.utils_view3d import SmartView3D, Pick_Base
from {0}dairin0d.utils_blender import Selection, MeshCache, BlUtil
from {0}dairin0d.utils_userinput import KeyMapUtils
from {0}dairin0d.utils_gl import cgl
from {0}dairin0d.utils_ui import NestedLayout, tag_redraw, rv3d_from_region, messagebox
from {0}dairin0d.bpy_inspect import prop, BlRna, BlEnums, BpyOp, bpy_struct
from {0}dairin0d.utils_accumulation import Aggregator, VectorAggregator
from {0}dairin0d.utils_addon import AddonManager, UIMonitor, addons_registry
""".format(dairin0d_location))

from .common import LeftRightPanel

from . import coordsystems
#from . import transform_tools

# CoordSystemPG is used in property declarations, so we have to import it at the top of this module.
# In other cases, importing can be placed at the bottom of the module to allow circular import.
from .coordsystems import *
#from .transform_tools import *

addon = AddonManager()

#============================================================================#

################################################################################################
################################################################################################
################################################################################################

# Insert functionality defined in this module
CoordSystemMatrix.get_coord_summary = staticmethod(lambda summary, dflt: TransformAggregator.get_coord_summary(summary, dflt))
CoordSystemMatrix.get_normal_summary = staticmethod(lambda summary: TransformAggregator.get_normal_summary(summary))
def find_ui_context(context):
    category = get_category()
    transform = category.find_transform(context.screen, context.area)
    return transform.ui_context
CoordSystemMatrix.find_ui_context = staticmethod(find_ui_context)
del find_ui_context

# =========================================================================== #
#                            < BATCH TRANSFORMS >                             #
# =========================================================================== #

class ObjectEmulator_Base: # emulates Object/PoseBone interface
    def __init__(self, element, id_data):
        self.element = element
        self.id_data = id_data
    
    def _dummy_set(self, value):
        pass
    
    id_data = None # assigned in constructor
    parent = property((lambda self: self.id_data), _dummy_set)
    parent_bone = property((lambda self: None), _dummy_set)
    parent_type = property((lambda self: 'OBJECT'), _dummy_set)
    parent_vertices = property((lambda self: (0, 0, 0)), _dummy_set)
    
    lock_location = property((lambda self: [False, False, False]), _dummy_set)
    lock_rotation = property((lambda self: [False, False, False]), _dummy_set)
    lock_rotation_w = property((lambda self: False), _dummy_set)
    lock_rotations_4d = property((lambda self: False), _dummy_set)
    lock_scale = property((lambda self: [False, False, False]), _dummy_set)
    
    def _get(self):
        return Vector()
    def _set(self, value):
        pass
    location = property(_get, _set)
    
    rotation_mode = 'QUATERNION' #property((lambda self: 'QUATERNION'), _dummy_set)
    
    def _get(self):
        aa = self.rotation_quaternion.normalized().to_axis_angle()
        return (aa[1], aa[0][0], aa[0][1], aa[0][2])
    def _set(self, value):
        self.rotation_quaternion = Quaternion(value[1:], value[0]).normalized()
    rotation_axis_angle = property(_get, _set)
    
    def _get(self):
        rotation_mode = self.rotation_mode
        if len(rotation_mode) != 3: rotation_mode = 'XYZ'
        return self.rotation_quaternion.normalized().to_euler(rotation_mode)
    def _set(self, value):
        rotation_mode = self.rotation_mode
        if len(rotation_mode) != 3: rotation_mode = 'XYZ'
        self.rotation_quaternion = Euler(value).to_quaternion().normalized()
    rotation_euler = property(_get, _set)
    
    def _get(self):
        return Quaternion((1, 0, 0, 0))
    def _set(self, value):
        pass
    rotation_quaternion = property(_get, _set)
    
    def _get(self):
        return Vector((1, 1, 1))
    def _set(self, value):
        pass
    scale = property(_get, _set)
    
    def _get(self):
        return Vector((1, 1, 1))
    def _set(self, value):
        pass
    dimensions = property(_get, _set)
    
    # x_axis
    # y_axis
    # z_axis
    
    def _get(self):
        return matrix_LRS(self.location, self.rotation_quaternion, self.scale)
    def _set(self, value):
        LRS = value.decompose()
        self.location = LRS[0]
        self.rotation_quaternion = LRS[1]
        self.scale = LRS[2]
    matrix = property(_get, _set)
    
    def _get(self):
        return self.id_data.matrix_world * self.matrix
    def _set(self, value):
        m_inv = matrix_inverted_safe(self.id_data.matrix_world)
        self.matrix = m_inv * value
    matrix_world = property(_get, _set)
    
    del _get
    del _set

class ObjectEmulator_Meta(ObjectEmulator_Base):
    _type_dof = {'BALL':0, 'CAPSULE':1, 'PLANE':2, 'ELLIPSOID':3, 'CUBE':3}
    _type_base = {'BALL':1, 'CAPSULE':0, 'PLANE':0, 'ELLIPSOID':1, 'CUBE':0}
    
    def _get(self):
        return bool(self._type_base[self.element.type])
    def _set(self, value):
        scale = self.scale
        self.element.type = ('ELLIPSOID' if value else 'CUBE') # others are reducible to these two
        self.scale = scale
    is_ellipsoid = property(_get, _set)
    
    def _get(self):
        return self.element.use_negative
    def _set(self, value):
        self.element.use_negative = value
    is_negative = property(_get, _set)
    
    def _get(self):
        return self.element.radius
    def _set(self, value):
        self.element.radius = value
    radius = property(_get, _set)
    
    def _get(self):
        return self.element.stiffness
    def _set(self, value):
        self.element.stiffness = value
    stiffness = property(_get, _set)
    
    def _get(self):
        return self.element.co
    def _set(self, value):
        self.element.co = value
    location = property(_get, _set)
    
    def _get(self):
        return self.element.rotation
    def _set(self, value):
        self.element.rotation = value
    rotation_quaternion = property(_get, _set)
    
    def _get(self):
        return self.id_data.rotation_mode
    def _set(self, value):
        self.id_data.rotation_mode = value
    rotation_mode = property(_get, _set)
    
    def _get(self):
        dof = self._type_dof[self.element.type]
        base = self._type_base[self.element.type]
        sx = (self.element.size_x if dof >= 1 else base)
        sy = (self.element.size_y if dof >= 2 else base)
        sz = (self.element.size_z if dof >= 3 else base)
        r = 1.0 # self.element.radius
        return Vector((sx, sy, sz)) * r
    def _set(self, value):
        base = self._type_base[self.element.type]
        self.element.type = ('ELLIPSOID' if base else 'CUBE') # others are reducible to these two
        sx = max(value[0], 0.0)
        sy = max(value[1], 0.0)
        sz = max(value[2], 0.0)
        r = 1.0 # max(max(sx, sy), sz)
        #self.element.radius = r
        self.element.size_x = sx / r
        self.element.size_y = sy / r
        self.element.size_z = sz / r
    dimensions = property(_get, _set)

class TransformAggregator:
    def __init__(self, context, csm):
        self.csm = csm
        self.queries = set(("count", "same"))
        
        self.mode = context.mode
        self.is_pose = (self.mode == 'POSE')
        
        self.process_active = getattr(self, self.mode+"_process_active", self._dummy)
        self.process_selected = getattr(self, self.mode+"_process_selected", self._dummy)
        self.finish = getattr(self, self.mode+"_finish", self._dummy)
        
        self.store = getattr(self, self.mode+"_store", self._dummy)
        self.restore = getattr(self, self.mode+"_restore", self._dummy)
        self.lock = getattr(self, self.mode+"_lock", self._dummy)
        
        self.set_prop = getattr(self, self.mode+"_set_prop", self._set_prop)
        
        self.coord_summary = getattr(self, self.mode+"_coord_summary", self._coord_summary)
        self.normal_summary = getattr(self, self.mode+"_normal_summary", self._normal_summary)
    
    def _dummy(self, *args, **kwargs):
        pass
    
    def init(self):
        self.queries.discard("active")
        self.queries.update(("min", "max", "center", "range", "mean", "stddev"))
        #self.queries.update(("min", "max", "center", "range", "mean", "stddev", "median"))
        self.iter_count = None
        self.iter_index = None
        getattr(self, self.mode+"_init", self._dummy)()
    
    def modify_vector(self, vector, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        if uniformity == 'OFFSET':
            return tuple(vector[i] if lock else (vector[i] + vector_delta[i]) for i, lock in enumerate(locks))
        elif uniformity == 'PROPORTIONAL':
            return tuple(vector[i] if lock else (vector_ref[i] + vector_scale[i] * (vector[i] - vector_ref[i])) for i, lock in enumerate(locks))
        else: # EQUAL
            return tuple(vector[i] if lock else vector_new[i] for i, lock in enumerate(locks))
    
    def _set_prop(self, context, prop_name, value, avoid_errors=True):
        for obj, select_names in Selection():
            if (not avoid_errors) or hasattr(obj, prop_name):
                setattr(obj, prop_name, value)
    
    def _coord_summary(self, summary, dflt=0.0):
        return Vector((dflt,dflt,dflt))
    def _normal_summary(self, summary):
        return Matrix.Identity(3)
    
    # ===== OBJECT ===== #
    def OBJECT_store(self, context):
        self.stored = []
        for obj, select_names in Selection():
            obj_LRS = self.csm.get_LRS(context, obj, self.rotation_mode, True)
            
            params = dict(
                L = obj_LRS[0],
                R = obj_LRS[1],
                S = obj_LRS[2],
                M = BlUtil.Object.matrix_world(obj),
                location = Vector(obj.location),
                rotation_axis_angle = Vector(obj.rotation_axis_angle),
                rotation_euler = Vector(obj.rotation_euler),
                rotation_quaternion = Vector(obj.rotation_quaternion),
                scale = Vector(obj.scale),
                dimensions = (Vector(obj.dimensions) if not self.is_pose else None),
            )
            self.stored.append((obj, params))
    
    def OBJECT_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        for obj, params in self.stored:
            # Applying both matrix and loc/rot/scale is a necessary measure:
            # * world matrix does not seem to be immediately updated by the basis loc/rot/scale,
            #   so we need to memorize and restore its original value
            # * we need non-changed basis values to stay exactly as they were (e.g. eulers can be > 180)
            BlUtil.Object.matrix_world_set(obj, params["M"])
            obj.location = params["location"]
            obj.rotation_axis_angle = params["rotation_axis_angle"]
            obj.rotation_euler = params["rotation_euler"]
            obj.rotation_quaternion = params["rotation_quaternion"]
            obj.scale = params["scale"]
            
            if vector_name == "location":
                L = self.modify_vector(params["L"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (L, None, None))
            elif vector_name == "rotation":
                R = self.modify_vector(params["R"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (None, R, None), self.rotation_mode)
            elif vector_name == "scale":
                S = self.modify_vector(params["S"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (None, None, S))
            elif (vector_name == "dimensions") and (not self.is_pose):
                # Important: use the copied data, not obj.dimensions directly (or there will be glitches)
                obj.dimensions = self.modify_vector(params["dimensions"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
    
    def OBJECT_lock(self, context, vector_name, axis_index, value):
        for obj, select_names in Selection():
            if vector_name == "location":
                obj.lock_location[axis_index] = value
            elif vector_name == "rotation":
                if axis_index == -1: # not one of actual components
                    obj.lock_rotations_4d = value
                elif axis_index == 0:
                    obj.lock_rotation_w = value
                else:
                    obj.lock_rotation[axis_index-1] = value
            elif vector_name == "scale":
                obj.lock_scale[axis_index] = value
    
    def OBJECT_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        rotation_mode_queries = {"count", "same", "modes"}
        
        self.location = Vector()
        self.rotation = Vector((1,0,0,0))
        self.scale = Vector((1,1,1))
        self.dimensions = Vector()
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_x = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_y = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_location = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_location_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_rotation = VectorAggregator(4, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_rotation_lock = VectorAggregator(4, 'BOOL', lock_queries)
        self.aggr_rotation_lock_4d = Aggregator('BOOL', lock_queries)
        self.aggr_rotation_mode = Aggregator('STRING', rotation_mode_queries)
        
        self.aggr_scale = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_scale_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_dimensions = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
    
    def OBJECT_process_active(self, context, obj):
        if not obj: return
        obj_LRS = self.csm.get_LRS(context, obj, self.last_rotation_mode, True)
        
        self.location = obj_LRS[0]
        self.rotation = obj_LRS[1]
        self.scale = obj_LRS[2]
        self.dimensions = (Vector(obj.dimensions) if (not self.is_pose) else Vector())
        
        if not self.is_pose:
            m = BlUtil.Object.matrix_world(obj)
            self.aggr_normal_x.add(m.col[0][:3])
            self.aggr_normal_y.add(m.col[1][:3])
            self.aggr_normal_z.add(m.col[2][:3])
    
    def OBJECT_process_selected(self, context, obj):
        obj_LRS = self.csm.get_LRS(context, obj, self.last_rotation_mode, True)
        
        self.aggr_location.add(obj_LRS[0])
        self.aggr_location_lock.add(obj.lock_location)
        
        self.aggr_rotation.add(obj_LRS[1])
        self.aggr_rotation_lock.add((obj.lock_rotation_w, obj.lock_rotation[0], obj.lock_rotation[1], obj.lock_rotation[2]))
        self.aggr_rotation_lock_4d.add(obj.lock_rotations_4d)
        self.aggr_rotation_mode.add(obj.rotation_mode)
        
        self.aggr_scale.add(obj_LRS[2])
        self.aggr_scale_lock.add(obj.lock_scale)
        
        if not self.is_pose: self.aggr_dimensions.add(obj.dimensions)
        
        if not self.is_pose:
            m = BlUtil.Object.matrix_world(obj)
            self.aggr_pivots.add(m.translation)
        else:
            # take into account only topmost selected bones
            parent = obj.parent
            while parent is not None:
                bone = obj.id_data.data.bones.get(parent.name)
                if bone and bone.select: return
                parent = parent.parent
            
            m = BlUtil.Object.matrix_world(obj)
            self.aggr_pivots.add(m.translation)
            self.aggr_normal_x.add(m.col[0].to_3d().normalized())
            self.aggr_normal_y.add(m.col[1].to_3d().normalized())
            self.aggr_normal_z.add(m.col[2].to_3d().normalized())
    
    last_rotation_mode = 'XYZ'
    def OBJECT_finish(self):
        cls = self.__class__
        if self.aggr_rotation_mode.mode: cls.last_rotation_mode = self.aggr_rotation_mode.mode
        self.rotation_mode = self.last_rotation_mode # make sure we have a local copy
    
    def OBJECT_coord_summary(self, summary, dflt=0.0):
        return Vector(self.aggr_pivots.get(summary, dflt, False))
    def OBJECT_normal_summary(self, summary):
        x = self.aggr_normal_x.get(summary, (1.0, 0.0, 0.0))
        y = self.aggr_normal_y.get(summary, (0.0, 1.0, 0.0))
        z = self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0))
        z = Vector(z).normalized()
        x = Vector(y).normalized().cross(z)
        y = z.cross(x)
        return matrix_compose(x, y, z)
    # ====================================================================== #
    
    # Currently, POSE aggregate attributes are exactly the same as OBJECT's,
    # except for the dimensions, and child-bones' Location displayed as inactive.
    POSE_store = OBJECT_store
    POSE_restore = OBJECT_restore
    POSE_lock = OBJECT_lock
    POSE_init = OBJECT_init
    POSE_process_active = OBJECT_process_active
    POSE_process_selected = OBJECT_process_selected
    POSE_finish = OBJECT_finish
    POSE_coord_summary = OBJECT_coord_summary # ? TODO: check if Blender behaves differently
    POSE_normal_summary = OBJECT_normal_summary # ? TODO: check if Blender behaves differently
    # ====================================================================== #
    
    # ===== OBJECT ===== #
    def EDIT_METABALL_set_prop(self, context, prop_name, value, avoid_errors=True):
        for obj, select_names in Selection():
            obj = (ObjectEmulator_Meta(obj, context.object) if obj else None) # DIFFERENT FROM OBJECT/POSE
            if (not avoid_errors) or hasattr(obj, prop_name):
                setattr(obj, prop_name, value)
    
    def EDIT_METABALL_store(self, context):
        self.stored = []
        for obj, select_names in Selection():
            obj = (ObjectEmulator_Meta(obj, context.object) if obj else None) # DIFFERENT FROM OBJECT/POSE
            obj_LRS = self.csm.get_LRS(context, obj, self.rotation_mode, True)
            
            params = dict(
                L = obj_LRS[0],
                R = obj_LRS[1],
                S = obj_LRS[2],
                M = BlUtil.Object.matrix_world(obj),
                location = Vector(obj.location),
                rotation_axis_angle = Vector(obj.rotation_axis_angle),
                rotation_euler = Vector(obj.rotation_euler),
                rotation_quaternion = Vector(obj.rotation_quaternion),
                scale = Vector(obj.scale),
                dimensions = (Vector(obj.dimensions) if not self.is_pose else None),
                radius = (obj.radius,),
                stiffness = (obj.stiffness,),
            )
            self.stored.append((obj, params))
    
    def EDIT_METABALL_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        for obj, params in self.stored:
            # Applying both matrix and loc/rot/scale is a necessary measure:
            # * world matrix does not seem to be immediately updated by the basis loc/rot/scale,
            #   so we need to memorize and restore its original value
            # * we need non-changed basis values to stay exactly as they were (e.g. eulers can be > 180)
            BlUtil.Object.matrix_world_set(obj, params["M"])
            obj.location = params["location"]
            obj.rotation_axis_angle = params["rotation_axis_angle"]
            obj.rotation_euler = params["rotation_euler"]
            obj.rotation_quaternion = params["rotation_quaternion"]
            obj.scale = params["scale"]
            
            obj.radius = params["radius"][0]
            obj.stiffness = params["stiffness"][0]
            
            if vector_name == "location":
                L = self.modify_vector(params["L"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (L, None, None))
            elif vector_name == "rotation":
                R = self.modify_vector(params["R"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (None, R, None), self.rotation_mode)
            elif vector_name == "scale":
                S = self.modify_vector(params["S"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                self.csm.set_LRS(context, obj, (None, None, S))
            elif (vector_name == "dimensions") and (not self.is_pose):
                # Important: use the copied data, not obj.dimensions directly (or there will be glitches)
                obj.dimensions = self.modify_vector(params["dimensions"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
            elif (vector_name == "radius"):
                obj.radius = self.modify_vector(params["radius"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
            elif (vector_name == "stiffness"):
                obj.stiffness = self.modify_vector(params["stiffness"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
    
    def EDIT_METABALL_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        rotation_mode_queries = {"count", "same", "modes"}
        
        self.location = Vector()
        self.rotation = Vector((1,0,0,0))
        self.scale = Vector((1,1,1))
        self.dimensions = Vector()
        self.radius = (2.0,)
        self.stiffness = (2.0,)
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_x = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_y = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_location = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_location_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_rotation = VectorAggregator(4, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_rotation_lock = VectorAggregator(4, 'BOOL', lock_queries)
        self.aggr_rotation_lock_4d = Aggregator('BOOL', lock_queries)
        self.aggr_rotation_mode = Aggregator('STRING', rotation_mode_queries)
        
        self.aggr_scale = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_scale_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_dimensions = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_radius = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_stiffness = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_is_negative = Aggregator('BOOL', lock_queries)
        self.aggr_is_ellipsoid = Aggregator('BOOL', lock_queries)
    
    def EDIT_METABALL_process_active(self, context, obj):
        if not obj: return
        obj = ObjectEmulator_Meta(obj, context.object) # DIFFERENT FROM OBJECT/POSE
        obj_LRS = self.csm.get_LRS(context, obj, self.last_rotation_mode, True)
        
        self.location = obj_LRS[0]
        self.rotation = obj_LRS[1]
        self.scale = obj_LRS[2]
        self.dimensions = (Vector(obj.dimensions) if (not self.is_pose) else Vector())
        self.radius = (obj.radius,)
        self.stiffness = (obj.stiffness,)
    
    def EDIT_METABALL_process_selected(self, context, obj):
        obj = (ObjectEmulator_Meta(obj, context.object) if obj else None) # DIFFERENT FROM OBJECT/POSE
        obj_LRS = self.csm.get_LRS(context, obj, self.last_rotation_mode, True)
        
        self.aggr_location.add(obj_LRS[0])
        self.aggr_location_lock.add(obj.lock_location)
        
        self.aggr_rotation.add(obj_LRS[1])
        self.aggr_rotation_lock.add((obj.lock_rotation_w, obj.lock_rotation[0], obj.lock_rotation[1], obj.lock_rotation[2]))
        self.aggr_rotation_lock_4d.add(obj.lock_rotations_4d)
        self.aggr_rotation_mode.add(obj.rotation_mode)
        
        self.aggr_scale.add(obj_LRS[2])
        self.aggr_scale_lock.add(obj.lock_scale)
        
        if not self.is_pose: self.aggr_dimensions.add(obj.dimensions)
        
        self.aggr_radius.add((obj.radius,))
        self.aggr_stiffness.add((obj.stiffness,))
        self.aggr_is_negative.add(obj.is_negative)
        self.aggr_is_ellipsoid.add(obj.is_ellipsoid)
        
        m = BlUtil.Object.matrix_world(obj)
        self.aggr_pivots.add(m.translation)
        self.aggr_normal_x.add(m.col[0].to_3d().normalized())
        self.aggr_normal_y.add(m.col[1].to_3d().normalized())
        self.aggr_normal_z.add(m.col[2].to_3d().normalized())
    
    def EDIT_METABALL_finish(self): # DIFFERENT FROM OBJECT/POSE
        self.rotation_mode = self.aggr_rotation_mode.mode or self.last_rotation_mode
    
    def EDIT_METABALL_coord_summary(self, summary, dflt=0.0):
        return Vector(self.aggr_pivots.get(summary, dflt, False))
    def EDIT_METABALL_normal_summary(self, summary):
        x = self.aggr_normal_x.get(summary, (1.0, 0.0, 0.0))
        y = self.aggr_normal_y.get(summary, (0.0, 1.0, 0.0))
        z = self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0))
        z = Vector(z).normalized()
        x = Vector(y).normalized().cross(z)
        y = z.cross(x)
        return matrix_compose(x, y, z)
    # ====================================================================== #
    
    def EDIT_ARMATURE_store(self, context):
        self.stored = []
        for obj, select_names in Selection():
            params = dict(
                head = Vector(obj.head),
                tail = Vector(obj.tail),
                head_L = self.csm.coord_to_L(context, context.object, obj.head, (obj.x_axis, obj.y_axis, obj.z_axis, obj.head)),
                tail_L = self.csm.coord_to_L(context, context.object, obj.tail, (obj.x_axis, obj.y_axis, obj.z_axis, obj.tail)),
                roll = (obj.roll,),
                envelope = Vector((obj.head_radius, obj.tail_radius, obj.envelope_distance, obj.envelope_weight)),
            )
            self.stored.append((obj, params))
    
    def EDIT_ARMATURE_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        for obj, params in self.stored:
            obj.head = params["head"]
            obj.tail = params["tail"]
            obj.roll = params["roll"]
            
            if vector_name == "head":
                head = self.modify_vector(params["head_L"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                obj.head = self.csm.coord_from_L(context, context.object, head, (obj.x_axis, obj.y_axis, obj.z_axis, obj.head))
            elif vector_name == "tail":
                tail = self.modify_vector(params["tail_L"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                obj.tail = self.csm.coord_from_L(context, context.object, tail, (obj.x_axis, obj.y_axis, obj.z_axis, obj.tail))
            elif vector_name == "roll":
                obj.roll = self.modify_vector(params["roll"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
            elif vector_name == "envelope":
                envelope = self.modify_vector(params["envelope"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                obj.head_radius, obj.tail_radius, obj.envelope_distance, obj.envelope_weight = envelope
    
    def EDIT_ARMATURE_lock(self, context, vector_name, axis_index, value):
        for obj, select_names in Selection():
            if vector_name in ("head", "tail"): obj.lock = value
    
    def EDIT_ARMATURE_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        
        self.head = Vector()
        self.tail = Vector()
        self.roll = (0.0,)
        self.envelope = Vector.Fill(4)
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_x = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_y = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_head = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_head_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_tail = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_tail_lock = VectorAggregator(3, 'BOOL', lock_queries)
        
        self.aggr_roll = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_envelope = VectorAggregator(4, 'NUMBER', self.queries, epsilon=epsilon)
    
    def EDIT_ARMATURE_process_active(self, context, obj):
        if not obj: return
        head = self.csm.coord_to_L(context, context.object, obj.head, (obj.x_axis, obj.y_axis, obj.z_axis, obj.head))
        tail = self.csm.coord_to_L(context, context.object, obj.tail, (obj.x_axis, obj.y_axis, obj.z_axis, obj.tail))
        self.head = head
        self.tail = tail
        self.roll = (obj.roll,)
        self.envelope = Vector((obj.head_radius, obj.tail_radius, obj.envelope_distance, obj.envelope_weight))
    
    def EDIT_ARMATURE_process_selected(self, context, obj):
        if obj.select:
            head = self.csm.coord_to_L(context, context.object, obj.head, (obj.x_axis, obj.y_axis, obj.z_axis, obj.head))
            tail = self.csm.coord_to_L(context, context.object, obj.tail, (obj.x_axis, obj.y_axis, obj.z_axis, obj.tail))
            
            self.aggr_head.add(head)
            self.aggr_head_lock.add((obj.lock, obj.lock, obj.lock))
            
            self.aggr_tail.add(tail)
            self.aggr_tail_lock.add((obj.lock, obj.lock, obj.lock))
            
            self.aggr_roll.add((obj.roll,))
            
            self.aggr_envelope.add((obj.head_radius, obj.tail_radius, obj.envelope_distance, obj.envelope_weight))
        
        m = BlUtil.Object.matrix_world(context.object)
        if obj.select_head: self.aggr_pivots.add(m * obj.head)
        if obj.select_tail: self.aggr_pivots.add(m * obj.tail)
        if obj.select:
            m3 = m.to_3x3()
            self.aggr_normal_x.add(m3 * obj.x_axis)
            self.aggr_normal_y.add(m3 * obj.y_axis)
            self.aggr_normal_z.add(m3 * obj.z_axis)
    
    def EDIT_ARMATURE_coord_summary(self, summary, dflt=0.0):
        return Vector(self.aggr_pivots.get(summary, dflt, False))
    def EDIT_ARMATURE_normal_summary(self, summary):
        x = self.aggr_normal_x.get(summary, (1.0, 0.0, 0.0))
        y = self.aggr_normal_y.get(summary, (0.0, 1.0, 0.0))
        z = self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0))
        z = Vector(z).normalized()
        x = Vector(y).normalized().cross(z)
        y = z.cross(x)
        return matrix_compose(x, y, z)
    # ====================================================================== #
    
    def EDIT_MESH_store(self, context):
        mesh = context.object.data
        bm = bmesh.from_edit_mesh(mesh)
        
        # Note: any references to elements become invalid after adding/deleting layers
        if not bm.verts.layers.bevel_weight.active:
            bm.verts.layers.bevel_weight.new("Bevel")
        if not bm.edges.layers.bevel_weight.active:
            bm.edges.layers.bevel_weight.new("Bevel")
        if not bm.edges.layers.crease.active:
            bm.edges.layers.crease.new("Crease")
        
        self.selection = Selection()
        self.selection.bmesh = bm
        self.stored = []
        for obj, select_names in self.selection:
            if isinstance(obj, bmesh.types.BMVert):
                params = dict(
                    co = Vector(obj.co),
                    location = self.csm.coord_to_L(context, context.object, obj.co, (None, None, obj.normal, obj.co)),
                    bevel = Vector((BlUtil.BMesh.layer_get(bm.verts.layers.bevel_weight, obj, 0.0), 0.0)),
                )
            elif isinstance(obj, bmesh.types.BMEdge):
                params = dict(
                    bevel = Vector((0.0, BlUtil.BMesh.layer_get(bm.edges.layers.bevel_weight, obj, 0.0))),
                    subsurf = (BlUtil.BMesh.layer_get(bm.edges.layers.crease, obj, 0.0),),
                )
            else:
                params = dict(
                )
            #self.stored.append((obj, params))
            self.stored.append(params)
    
    def EDIT_MESH_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        mesh = context.object.data
        bm = bmesh.from_edit_mesh(mesh)
        self.selection = Selection()
        index = 0
        #for obj, params in self.stored:
        for obj, select_names in self.selection:
            params = self.stored[index]
            index += 1
            if isinstance(obj, bmesh.types.BMVert):
                if vector_name == "location":
                    obj.co = params["co"]
                    location = self.modify_vector(params["location"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                    obj.co = self.csm.coord_from_L(context, context.object, location, (None, None, obj.normal, obj.co))
                elif vector_name == "bevel":
                    bevel = self.modify_vector(params["bevel"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                    BlUtil.BMesh.layer_set(bm.verts.layers.bevel_weight, obj, bevel[0])
            elif isinstance(obj, bmesh.types.BMEdge):
                if vector_name == "bevel":
                    bevel = self.modify_vector(params["bevel"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                    BlUtil.BMesh.layer_set(bm.edges.layers.bevel_weight, obj, bevel[1])
                elif vector_name == "subsurf":
                    subsurf = self.modify_vector(params["subsurf"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                    BlUtil.BMesh.layer_set(bm.edges.layers.crease, obj, subsurf[0])
        
        if vector_name == "location":
            bmesh.update_edit_mesh(context.object.data, tessface=True, destructive=False)
    
    def EDIT_MESH_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        
        self.location = Vector()
        self.bevel = Vector.Fill(2)
        self.subsurf = (0.0,)
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_verts = [None, None, None]
        self.aggr_normal_effective_count = 0
        
        self.aggr_location = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_bevel = VectorAggregator(2, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_subsurf = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.bm = None
    
    def EDIT_MESH_process_active(self, context, obj):
        if not self.bm:
            self.bm = addons_registry._sel_iter.selection.bmesh
            self.layers_vert_bevel = self.bm.verts.layers.bevel_weight
            self.layers_edge_bevel = self.bm.edges.layers.bevel_weight
            self.layers_edge_crease = self.bm.edges.layers.crease
        
        if not obj: obj = self.bm.faces.active
        if not obj: return
        
        if isinstance(obj, bmesh.types.BMVert):
            co = Vector(obj.co)
            normal = Vector(obj.normal)
            self.location = self.csm.coord_to_L(context, context.object, co, (None, None, normal, co))
            self.bevel[0] = BlUtil.BMesh.layer_get(self.layers_vert_bevel, obj, 0.0)
        elif isinstance(obj, bmesh.types.BMEdge):
            verts = tuple(obj.verts)
            co0 = Vector(verts[0].co)
            co1 = Vector(verts[1].co)
            self.bevel[1] = BlUtil.BMesh.layer_get(self.layers_edge_bevel, obj, 0.0)
            self.subsurf = (BlUtil.BMesh.layer_get(self.layers_edge_crease, obj, 0.0),)
        elif isinstance(obj, bmesh.types.BMFace):
            verts = tuple(obj.verts)
            center = sum((Vector(v.co) for v in verts), Vector()) * (1.0 / len(verts))
            normal = Vector(obj.normal)
    
    def EDIT_MESH_process_selected(self, context, obj):
        if not self.bm:
            self.bm = addons_registry._sel_iter.selection.bmesh
            self.layers_vert_bevel = self.bm.verts.layers.bevel_weight
            self.layers_edge_bevel = self.bm.edges.layers.bevel_weight
            self.layers_edge_crease = self.bm.edges.layers.crease
        
        if isinstance(obj, bmesh.types.BMVert):
            co = Vector(obj.co)
            normal = Vector(obj.normal)
            
            location = self.csm.coord_to_L(context, context.object, co, (None, None, normal, co))
            self.aggr_location.add(location)
            self.aggr_bevel.add(BlUtil.BMesh.layer_get(self.layers_vert_bevel, obj, 0.0), 0)
            
            self.aggr_pivots.add(co)
            self.aggr_normal_z.add(normal)
            
            if self.aggr_pivots.count <= 3:
                history = self.bm.select_history
                is_active = ((obj == history[len(history)-1]) if history else False)
                selected_edges = sum(int(edge.select) for edge in obj.link_edges)
                if self.aggr_normal_effective_count == 0:
                    self.aggr_normal_verts[0] = (co, normal, Vector(), is_active, selected_edges)
                    self.aggr_normal_effective_count = 1
                else:
                    delta_dir = (co - self.aggr_normal_verts[0][0]).normalized()
                    if delta_dir.magnitude > 0.5:
                        i = self.aggr_normal_effective_count
                        self.aggr_normal_verts[i] = (co, normal, delta_dir, is_active, selected_edges)
                        self.aggr_normal_effective_count += 1
        elif isinstance(obj, bmesh.types.BMEdge):
            self.aggr_bevel.add(BlUtil.BMesh.layer_get(self.layers_edge_bevel, obj, 0.0), 1)
            self.aggr_subsurf.add((BlUtil.BMesh.layer_get(self.layers_edge_crease, obj, 0.0),))
        elif isinstance(obj, bmesh.types.BMFace):
            pass # currently no statistics from faces are gathered
    
    def EDIT_MESH_finish(self): # DIFFERENT FROM OBJECT/POSE
        self.bm = None
        self.layers_vert_bevel = None
        self.layers_edge_bevel = None
        self.layers_edge_crease = None
    
    def EDIT_MESH_coord_summary(self, summary, dflt=0.0):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        return m * Vector(self.aggr_pivots.get(summary, dflt, False))
    def EDIT_MESH_normal_summary(self, summary):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        m3 = m.to_3x3()
        if self.aggr_normal_effective_count == 2:
            v0 = self.aggr_normal_verts[0]
            v1 = self.aggr_normal_verts[1]
            dv = (-v1[2] if v0[3] else v1[2])
            z = (m3 * dv)
            normal = Vector(self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0)))
            normal.normalize()
            y = (m3 * normal if normal.magnitude > 0.5 else None)
            x, y, z = orthogonal_XYZ(None, y, z, "z")
        elif self.aggr_normal_effective_count == 3:
            v0 = self.aggr_normal_verts[0]
            v1 = self.aggr_normal_verts[1]
            v2 = self.aggr_normal_verts[2]
            if (v0[4] >= v1[4]) and (v0[4] >= v2[4]):
                dv1 = v1[2]
                dv2 = v2[2]
            elif (v1[4] >= v2[4]):
                dv1 = (v0[0] - v1[0]).normalized()
                dv2 = (v2[0] - v1[0]).normalized()
            else:
                dv1 = (v0[0] - v2[0]).normalized()
                dv2 = (v1[0] - v2[0]).normalized()
            ort = dv1.cross(dv2)
            normal = Vector(self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0)))
            if normal.dot(ort) < 0: ort = -ort
            z = m3 * ort
            y = m3 * (dv1 if v1[4] else dv2)
            x, y, z = orthogonal_XYZ(None, y, z, "z")
        else:
            normal = Vector(self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0)))
            normal.normalize()
            if normal.magnitude < 0.5: normal = Vector((0,0,1)) # just some fallback
            x, y, z = orthogonal_XYZ(None, None, m3 * normal, "z")
        return matrix_compose(x.normalized(), y.normalized(), z.normalized())
    # ====================================================================== #
    
    def EDIT_LATTICE_store(self, context):
        self.stored = []
        for obj, select_names in Selection():
            co = Vector(obj.co_deform)
            params = dict(
                co = co,
                location = self.csm.coord_to_L(context, context.object, co, (None, None, None, co)),
                weight = (obj.weight_softbody,),
            )
            self.stored.append((obj, params))
    
    def EDIT_LATTICE_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        for obj, params in self.stored:
            if vector_name == "location":
                obj.co_deform = params["co"]
                location = self.modify_vector(params["location"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                obj.co_deform = self.csm.coord_from_L(context, context.object, location, (None, None, None, obj.co_deform))
            elif vector_name == "weight":
                obj.weight_softbody = self.modify_vector(params["weight"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
    
    def EDIT_LATTICE_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        
        self.location = Vector()
        self.weight = (0.0,)
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_x = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_y = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_location = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_weight = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
    
    def EDIT_LATTICE_process_active(self, context, obj):
        if not obj: return
        
        co = Vector(obj.co_deform)
        self.location = self.csm.coord_to_L(context, context.object, co, (None, None, None, co))
        
        self.weight = (obj.weight_softbody,)
    
    def EDIT_LATTICE_process_selected(self, context, obj):
        co = Vector(obj.co_deform)
        location = self.csm.coord_to_L(context, context.object, co, (None, None, None, co))
        self.aggr_location.add(location)
        
        self.aggr_weight.add((obj.weight_softbody,))
        
        self.aggr_pivots.add(location)
    
    def EDIT_LATTICE_coord_summary(self, summary, dflt=0.0):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        return m * Vector(self.aggr_pivots.get(summary, dflt, False))
    def EDIT_LATTICE_normal_summary(self, summary):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        m3 = m.to_3x3()
        x = self.aggr_normal_x.get(summary, (1.0, 0.0, 0.0))
        y = self.aggr_normal_y.get(summary, (0.0, 1.0, 0.0))
        z = self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0))
        z = Vector(z).normalized()
        x = Vector(y).normalized().cross(z)
        y = z.cross(x)
        return matrix_compose((m3*x).normalized(), (m3*y).normalized(), (m3*z).normalized())
    # ====================================================================== #
    
    def EDIT_CURVE_store(self, context):
        self.stored = []
        for obj, select_names in Selection():
            xyztw = BlUtil.Spline.point_xyztw(obj, context.object)
            if isinstance(obj, bpy.types.SplinePoint):
                co = Vector(obj.co)
                pos = self.csm.coord_to_L(context, context.object, co.to_3d(), xyztw[:4])
                params = dict(
                    xyztw = xyztw,
                    co = co, pos = Vector((pos[0], pos[1], pos[2], xyztw[4])),
                    weight = (obj.weight_softbody,),
                    radius = (obj.radius,),
                    tilt = (obj.tilt,),
                )
            else: # bpy.types.BezierSplinePoint
                co = Vector(obj.co)
                handle_left = Vector(obj.handle_left)
                handle_right = Vector(obj.handle_right)
                pos = self.csm.coord_to_L(context, context.object, co, xyztw[:4])
                pos_left = self.csm.coord_to_L(context, context.object, handle_left, xyztw[:4])
                pos_right = self.csm.coord_to_L(context, context.object, handle_right, xyztw[:4])
                params = dict(
                    xyztw = xyztw,
                    co = co, pos = pos,
                    handle_left = handle_left, pos_left = pos_left,
                    handle_right = handle_right, pos_right = pos_right,
                    weight = (obj.weight_softbody,),
                    radius = (obj.radius,),
                    tilt = (obj.tilt,),
                )
            self.stored.append((obj, params))
    
    def EDIT_CURVE_restore(self, context, vector_name, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks):
        for obj, params in self.stored:
            if vector_name == "location":
                xyztw = params["xyztw"]
                if isinstance(obj, bpy.types.SplinePoint):
                    obj.co = params["co"]
                    pos4 = self.modify_vector(params["pos"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                    pos = self.csm.coord_from_L(context, context.object, pos4[:3], xyztw[:4])
                    obj.co = Vector((pos[0], pos[1], pos[2], pos4[3]))
                else: # bpy.types.BezierSplinePoint
                    obj.co = params["co"]
                    obj.handle_left = params["handle_left"]
                    obj.handle_right = params["handle_right"]
                    if obj.select_control_point:
                        pos = params["pos"]
                        pos4 = Vector((pos[0], pos[1], pos[2], 0.0))
                        pos4 = self.modify_vector(pos4, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                        obj.co = self.csm.coord_from_L(context, context.object, pos4[:3], xyztw[:4])
                    if obj.select_left_handle or obj.select_control_point:
                        pos = params["pos_left"]
                        pos4 = Vector((pos[0], pos[1], pos[2], 0.0))
                        pos4 = self.modify_vector(pos4, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                        obj.handle_left = self.csm.coord_from_L(context, context.object, pos4[:3], xyztw[:4])
                    if obj.select_right_handle or obj.select_control_point:
                        pos = params["pos_right"]
                        pos4 = Vector((pos[0], pos[1], pos[2], 0.0))
                        pos4 = self.modify_vector(pos4, uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
                        obj.handle_right = self.csm.coord_from_L(context, context.object, pos4[:3], xyztw[:4])
            elif vector_name == "weight":
                obj.weight_softbody = self.modify_vector(params["weight"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
            elif vector_name == "radius":
                obj.radius = self.modify_vector(params["radius"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
            elif vector_name == "tilt":
                obj.tilt = self.modify_vector(params["tilt"], uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)[0]
    
    def EDIT_CURVE_init(self):
        epsilon = addon.preferences.epsilon
        lock_queries = {"count", "same", "mean"}
        
        self.location = Vector.Fill(4)
        self.weight = (0.0,)
        self.radius = (0.0,)
        self.tilt = (0.0,)
        
        self.aggr_pivots = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_x = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_y = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_normal_z = VectorAggregator(3, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_location = VectorAggregator(4, 'NUMBER', self.queries, epsilon=epsilon)
        
        self.aggr_weight = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_radius = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
        self.aggr_tilt = VectorAggregator(1, 'NUMBER', self.queries, epsilon=epsilon)
    
    def EDIT_CURVE_process_active(self, context, obj):
        if not obj: return
        
        xyztw = BlUtil.Spline.point_xyztw(obj, context.object)
        pos = self.csm.coord_to_L(context, context.object, xyztw[3], xyztw[:4])
        self.location = Vector((pos[0], pos[1], pos[2], (xyztw[4] or 0.0)))
        
        self.weight = (obj.weight_softbody,)
        self.radius = (obj.radius,)
        self.tilt = (obj.tilt,)
    
    def EDIT_CURVE_process_selected(self, context, obj):
        xyztw = BlUtil.Spline.point_xyztw(obj, context.object)
        pos = self.csm.coord_to_L(context, context.object, xyztw[3], xyztw[:4])
        if xyztw[4] is None:
            self.aggr_location.add(pos[0], 0)
            self.aggr_location.add(pos[1], 1)
            self.aggr_location.add(pos[2], 2)
        else:
            self.aggr_location.add(Vector((pos[0], pos[1], pos[2], xyztw[4])))
        
        self.aggr_weight.add((obj.weight_softbody,))
        self.aggr_radius.add((obj.radius,))
        self.aggr_tilt.add((obj.tilt,))
        
        self.aggr_pivots.add(xyztw[3])
        if xyztw[0]: self.aggr_normal_x.add(xyztw[0])
        if xyztw[1]: self.aggr_normal_y.add(xyztw[1])
        if xyztw[2]: self.aggr_normal_z.add(xyztw[2])
    
    def EDIT_CURVE_coord_summary(self, summary, dflt=0.0):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        return m * Vector(self.aggr_pivots.get(summary, dflt, False))
    def EDIT_CURVE_normal_summary(self, summary):
        m = BlUtil.Object.matrix_world(bpy.context.object)
        m3 = m.to_3x3()
        x = self.aggr_normal_x.get(summary, (1.0, 0.0, 0.0))
        y = self.aggr_normal_y.get(summary, (0.0, 1.0, 0.0))
        z = self.aggr_normal_z.get(summary, (0.0, 0.0, 1.0))
        z = Vector(z).normalized()
        x = Vector(y).normalized().cross(z)
        y = z.cross(x)
        return matrix_compose((m3*x).normalized(), (m3*y).normalized(), (m3*z).normalized())
    
    EDIT_SURFACE_store = EDIT_CURVE_store
    EDIT_SURFACE_restore = EDIT_CURVE_restore
    EDIT_SURFACE_init = EDIT_CURVE_init
    EDIT_SURFACE_process_active = EDIT_CURVE_process_active
    EDIT_SURFACE_process_selected = EDIT_CURVE_process_selected
    EDIT_SURFACE_coord_summary = EDIT_CURVE_coord_summary
    EDIT_SURFACE_normal_summary = EDIT_CURVE_normal_summary
    # ====================================================================== #
    
    tfm_aggr_map = {}
    tfm_aggrs = []
    _global_aggr = None
    
    @classmethod
    def get_coord_summary(cls, summary, dflt=0.0):
        tfm_aggr = cls._global_aggr
        if not tfm_aggr: return Vector((dflt,dflt,dflt))
        return tfm_aggr.coord_summary(summary, dflt)
    @classmethod
    def get_normal_summary(cls, summary):
        tfm_aggr = cls._global_aggr
        if not tfm_aggr: return Matrix.Identity(3)
        return tfm_aggr.normal_summary(summary)
    
    @classmethod
    def iter_transforms(cls, category, coordsystem_manager):
        coordsys_name_default = coordsystem_manager.coordsystem.selector
        coordsystems = coordsystem_manager.coordsystems
        for transform in category.transforms:
            if not transform.is_v3d: continue
            coordsys_name = (transform.coordsystem_selector.selector
                if transform.use_pinned_coordsystem else coordsys_name_default)
            coordsys = coordsystems.get(coordsys_name)
            if coordsys: yield transform, coordsys
    
    @classmethod
    def job(cls, event, item):
        context = bpy.context
        if event == 1: # SELECTED
            for tfm_aggr in cls.tfm_aggrs:
                tfm_aggr.process_selected(context, item)
        elif event == 0: # ACTIVE
            for tfm_aggr in cls.tfm_aggrs:
                tfm_aggr.process_active(context, item)
        else: # RESET or FINISHED
            coordsystem_manager = get_coordsystem_manager(context)
            
            category = get_category()
            category.transforms_ensure_order(context.screen)
            
            if event == -1: # FINISHED
                for transform, coordsys in cls.iter_transforms(category, coordsystem_manager):
                    transformExt = addon[transform]
                    coordsys_key = coordsys.unique_key(transformExt)
                    tfm_aggr = cls.tfm_aggr_map.get(coordsys_key)
                    if tfm_aggr: # coordsystem might have changed in the meantime
                        tfm_aggr.finish()
                        # Don't interfere while user is changing some value
                        if not UIMonitor.user_interaction: transform.apply(tfm_aggr)
                cls._global_aggr = cls.tfm_aggr_map.get(("", None))
            else: # RESET
                cls.tfm_aggr_map = {}
                
                csm = CoordSystemMatrix(None)
                tfm_aggr = TransformAggregator(context, csm)
                cls.tfm_aggr_map[("", None)] = tfm_aggr
                
                for transform, coordsys in cls.iter_transforms(category, coordsystem_manager):
                    transformExt = addon[transform]
                    coordsys_key = coordsys.unique_key(transformExt)
                    tfm_aggr = cls.tfm_aggr_map.get(coordsys_key)
                    if tfm_aggr is None:
                        sv = None
                        if coordsys_key[1]:
                            sv = SmartView3D(use_camera_axes=True, **transform.ui_context)
                        csm = CoordSystemMatrix(coordsys, sv)
                        tfm_aggr = TransformAggregator(context, csm)
                        cls.tfm_aggr_map[coordsys_key] = tfm_aggr
                    tfm_aggr.queries.update(transform.summaries)
                
                cls.tfm_aggrs = list(cls.tfm_aggr_map.values())
                for tfm_aggr in cls.tfm_aggrs:
                    tfm_aggr.init()

addon.selection_job(TransformAggregator.job)

# Make sure UI Monitor is active (it is inactive if there are no callbacks)
@addon.ui_monitor
def ui_monitor(context, event, UIMonitor):
    if 'MOUSEMOVE' in event.type:
        if (context.area == 'VIEW_3D') and (context.region.type == 'WINDOW'):
            category = get_category()
            transform = category.find_transform(context.screen, context.area)
            if transform:
                transformExt = addon[transform]
                transformExt.window = context.window
                transformExt.screen = context.screen
                transformExt.space_data = context.space_data
                transformExt.region = context.region
                transformExt.region_data = context.region_data
        
        if UIMonitor.last_rv3d_context:
            rv3d_context = AttributeHolder(context, **UIMonitor.last_rv3d_context)
            csm = CoordSystemMatrix.current(rv3d_context)
            matrix = csm.final_matrix()
            BlUtil.Orientation.update(rv3d_context, "System", matrix)

def SummaryValuePG(default, representations, **kwargs):
    tooltip = "Click: independent, Shift+Click: offset, Alt+Click: proportional, Ctrl+Click or Shift+Alt+Click: equal"
    kwargs = dict(kwargs, description=(kwargs.get("description", "")+tooltip))
    if "update" not in kwargs: kwargs["update"] = True
    
    @addon.PropertyGroup
    class cls:
        value = default | -prop(**kwargs)
        
        def draw(self, layout, prop_name="value"):
            layout.prop(self, prop_name)
    
    def dummy_get(self):
        return default
    def dummy_set(self, value):
        pass
    cls.dummy = default | -prop(get=dummy_get, set=dummy_set, **dict(kwargs, name="--"))
    
    def _get(self):
        return self.value
    
    def _set(self, value):
        id_data = self.id_data
        path_parts = self.path_from_id().split(".")
        tfm_mode = id_data.path_resolve(".".join(path_parts[:-2]))
        
        if not UIMonitor.user_interaction:
            UIMonitor.user_interaction = True
            
            axis_name = path_parts[-1]
            axis_parts = axis_name.split("[")
            axis_name = axis_parts[0]
            summary_index = int(axis_parts[1].strip("[]"))
            
            vector_name = path_parts[-2]
            
            transform = id_data.path_resolve(".".join(path_parts[:-3]))
            
            # Ctrl+clicking on a numeric value makes it go into a "text editing mode"
            # no mater where the user clicked or if the property was dragged.
            if UIMonitor.ctrl or (UIMonitor.shift and UIMonitor.alt):
                uniformity = 'EQUAL'
            elif UIMonitor.shift:
                uniformity = 'OFFSET'
            elif UIMonitor.alt:
                uniformity = 'PROPORTIONAL'
            else:
                uniformity = 'INDEPENDENT'
            
            tfm_mode.begin(transform, vector_name, axis_name, summary_index, uniformity)
        
        tfm_mode.modify(value)
    
    for representation in representations:
        subtype = representation.get("subtype", 'NONE')
        setattr(cls, subtype.lower(), default | -prop(get=_get, set=_set, **dict(kwargs, **representation)))
    
    return cls

def LockPG(default_uniformity=False):
    disable_uniformity = (default_uniformity is None)
    if disable_uniformity: default_uniformity = True
    
    @addon.PropertyGroup
    class cls:
        lock_uniformity = default_uniformity | -prop(update=True)
        lock_transformation = False | -prop(update=True)
        
        def _get(self):
            return self.lock_uniformity
        def _set(self, value):
            if UIMonitor.ctrl:
                id_data = self.id_data
                path_parts = self.path_from_id().split(".")
                tfm_mode = id_data.path_resolve(".".join(path_parts[:-2]))
                axis_name = path_parts[-1].split("_")[0]
                vector_name = path_parts[-2]
                tfm_mode.modify_lock(vector_name, axis_name, not self.lock_transformation)
            else:
                if not disable_uniformity: self.lock_uniformity = value
        value = False | -prop(get=_get, set=_set, description="Click: lock uniformity, Ctrl+Click: lock transformation")
    
    return cls

@addon.PropertyGroup
class Lock4dPG:
    lock_4d = False | -prop(update=True)
    
    def _get(self):
        return self.lock_4d
    def _set(self, value):
        id_data = self.id_data
        path_parts = self.path_from_id().split(".")
        tfm_mode = id_data.path_resolve(".".join(path_parts[:-2]))
        axis_name = path_parts[-1].split("_")[0]
        vector_name = path_parts[-2]
        tfm_mode.modify_lock(vector_name, axis_name, value)
    value = False | -prop(get=_get, set=_set, description="Click: enable/disable locking 4-component rotations as eulers")

@addon.PropertyGroup
class RotationModePG:
    items = [
        ('QUATERNION', "Quaternion (WXYZ)", "No Gimbal Lock"),
        ('XYZ', "XYZ Euler", "XYZ Rotation Order - prone to Gimbal Lock"),
        ('XZY', "XZY Euler", "XZY Rotation Order - prone to Gimbal Lock"),
        ('YXZ', "YXZ Euler", "YXZ Rotation Order - prone to Gimbal Lock"),
        ('YZX', "YZX Euler", "YZX Rotation Order - prone to Gimbal Lock"),
        ('ZXY', "ZXY Euler", "ZXY Rotation Order - prone to Gimbal Lock"),
        ('ZYX', "ZYX Euler", "ZYX Rotation Order - prone to Gimbal Lock"),
        ('AXIS_ANGLE', "Axis Angle", "Axis Angle (W+XYZ), defines a rotation around some axis defined by 3D-Vector"),
    ]
    mode = 'XYZ' | -prop(items=items, update=True)
    
    # Note: the Enum get/set methods must return ints instead of strings/sets
    def _get(self):
        for i, item in enumerate(self.items):
            if item[0] == self.mode: return i+1
    def _set(self, value):
        value = self.items[value-1][0]
        id_data = self.id_data
        path_parts = self.path_from_id().split(".")
        tfm_mode = id_data.path_resolve(".".join(path_parts[:-2]))
        tfm_mode.modify_prop("rotation_mode", value)
    value = 'XYZ' | -prop(items=items, get=_get, set=_set, description="Rotation mode")

def SummaryVectorPG(title, axes, is_rotation=False, folded=False, resetable=True, extra_operators=None):
    @addon.PropertyGroup
    class cls:
        def get_vector(self, si):
            return tuple(getattr(self, axis_name)[si].value for axis_name in self.axis_names)
        def set_vector(self, si, value):
            epsilon = 1e-6 # NOT addon.preferences.epsilon
            for i, axis_name in enumerate(self.axis_names):
                setattr_cmp(getattr(self, axis_name)[si], "value", value[i], epsilon)
        
        def _get_lock_uniformity(self):
            return tuple(getattr(self, axis_name+"_lock").lock_uniformity for axis_name in self.axis_names)
        def _set_lock_uniformity(self, value):
            for i, axis_name in enumerate(self.axis_names):
                if self.axis_defaults_uniformity[i] is None: continue # this axis should NEVER participate in uniformity
                setattr_cmp(getattr(self, axis_name+"_lock"), "lock_uniformity", value[i])
        lock_uniformity = property(_get_lock_uniformity, _set_lock_uniformity)
        
        def _get_lock_transformation(self):
            return tuple(getattr(self, axis_name+"_lock").lock_transformation for axis_name in self.axis_names)
        def _set_lock_transformation(self, value):
            for i, axis_name in enumerate(self.axis_names):
                setattr_cmp(getattr(self, axis_name+"_lock"), "lock_transformation", value[i])
        lock_transformation = property(_get_lock_transformation, _set_lock_transformation)
        
        def match_summaries(self, summaries, axis=None):
            if axis is None:
                for axis_name in self.axis_names:
                    self.match_summaries(summaries, getattr(self, axis_name))
            elif len(axis) != len(summaries):
                axis.clear()
                for i in range(len(summaries)):
                    axis.add()
        
        def draw_axis(self, layout, summaries, axis_i, axis_id, prop_name="value", lock_enabled=True):
            axis = getattr(self, axis_id)
            axis_lock = getattr(self, axis_id+"_lock")
            
            self.match_summaries(summaries, axis)
            
            vector_same = self.get("vector:same")
            axis_same = (True if vector_same is None else vector_same[axis_i])
            lock_same = self.get("lock:same")
            lock_same = (True if lock_same is None else lock_same[axis_i])
            
            lock_allowed = (self.axis_defaults_uniformity[axis_i] is not None)
            
            with layout.row(True):
                with layout.row(True)(alert=not axis_same, enabled=(prop_name != "dummy")):
                    for axis_item in axis:
                        axis_item.draw(layout, prop_name)
                
                with layout.row(True)(alert=not lock_same, active=(lock_enabled and lock_allowed)):
                    icon = ('LOCKED' if axis_lock.lock_transformation else 'UNLOCKED')
                    layout.prop(axis_lock, "value", text="", icon=icon, toggle=True)
    
    axis_names = []
    axis_subtypes = []
    axis_defaults = []
    axis_defaults_uniformity = []
    for axis in axes:
        name, default, default_uniformity, representations, kwargs = axis
        kwargs = dict({"name":name}, **kwargs)
        
        setattr(cls, name, [SummaryValuePG(default, representations, **kwargs)] | -prop())
        setattr(cls, name+"_lock", LockPG(default_uniformity) | -prop())
        
        axis_names.append(name)
        axis_subtypes.append(tuple(r["subtype"].lower() for r in representations))
        axis_defaults.append(default)
        axis_defaults_uniformity.append(default_uniformity)
    
    cls.axis_names = tuple(axis_names)
    cls.axis_subtypes = tuple(axis_subtypes)
    cls.axis_defaults = tuple(axis_defaults)
    cls.axis_defaults_uniformity = tuple(axis_defaults_uniformity)
    
    cls.resetable = resetable
    cls.extra_operators = extra_operators
    
    if is_rotation:
        cls.w4d_lock = Lock4dPG | -prop()
        cls.mode = RotationModePG | -prop()
    
    def draw(self, layout, summaries):
        id_data = self.id_data
        path_parts = self.path_from_id().split(".")
        self_prop_name = path_parts[-1]
        
        with layout.row(True):
            with layout.fold("", ("row", True), folded, key=title):
                is_folded = layout.folded
            with layout.row(True)(alignment='LEFT'):
                op = layout.operator("object.batch_transform_vector_menu", text=title, emboss=False)
                op.vector = self_prop_name
                op.title = title
            with layout.row()(alignment='RIGHT', enabled=self.resetable):
                op = layout.operator("object.batch_transform_reset_vectors", text="", icon='LOAD_FACTORY')
                op.vectors = self_prop_name
        
        if (not is_folded) and summaries:
            with layout.column(True):
                if not is_rotation:
                    for i in range(len(self.axis_names)):
                        self.draw_axis(layout, summaries, i, self.axis_names[i], self.axis_subtypes[i][0])
                else:
                    rotation_mode = self.mode.mode
                    is_euler = (rotation_mode not in ('QUATERNION', 'AXIS_ANGLE'))
                    w4d_lock_same = self.get("w4d_lock:same", True)
                    mode_same = self.get("mode:same", True)
                    
                    if is_euler:
                        self.draw_axis(layout, summaries, 0, "w", "dummy", self.w4d_lock.lock_4d)
                        self.draw_axis(layout, summaries, 1, "x", "angle")
                        self.draw_axis(layout, summaries, 2, "y", "angle")
                        self.draw_axis(layout, summaries, 3, "z", "angle")
                    else:
                        if rotation_mode == 'QUATERNION':
                            self.draw_axis(layout, summaries, 0, "w", "none", self.w4d_lock.lock_4d)
                        else:
                            self.draw_axis(layout, summaries, 0, "w", "angle", self.w4d_lock.lock_4d)
                        self.draw_axis(layout, summaries, 1, "x", "none")
                        self.draw_axis(layout, summaries, 2, "y", "none")
                        self.draw_axis(layout, summaries, 3, "z", "none")
                    
                    with layout.row(True):
                        with layout.row(True)(alert=not mode_same):
                            layout.prop(self.mode, "value", text="")
                        with layout.row(True)(alert=not w4d_lock_same, active=(not is_euler), scale_x=0.1):
                            layout.prop(self.w4d_lock, "value", text="4L", toggle=True)
    
    cls.draw = draw
    
    return cls

@addon.Operator(idname="object.batch_transform_vector_menu", options={'INTERNAL'}, description=
"Click: Vector menu")
def Operator_Vector_Menu(self, context, event, vector="", title=""):
    def draw_popup_menu(self, context):
        category = get_category()
        transform = category.find_transform(context.screen, context.area)
        
        tfm_mode = transform.get_transform_mode(context.mode)
        if not tfm_mode: return
        
        vector_prop = getattr(tfm_mode, vector)
        if not vector_prop: return
        
        layout = NestedLayout(self.layout)
        
        if vector_prop.extra_operators:
            for op_args, op_props in vector_prop.extra_operators:
                op_name = op_args["operator"]
                if not BpyOp(op_name).poll(): continue
                op = layout.operator(**op_args)
                for k, v in op_props.items():
                    setattr(op, k, v)
        
        #layout.operator("object.batch_transform_summary_copy", text="Copy", icon='COPYDOWN')
        #layout.operator("object.batch_transform_summary_paste", text="Paste", icon='PASTEDOWN')
        #layout.operator("object.batch_transform_summary_paste", text="+ Paste", icon='PASTEDOWN')
        #layout.operator("object.batch_transform_summary_paste", text=" \u2013 Paste", icon='PASTEDOWN')
        #layout.operator("object.batch_transform_summary_paste", text=" * Paste", icon='PASTEDOWN')
        #layout.operator("object.batch_transform_summary_paste", text="\u00F7 Paste", icon='PASTEDOWN')
        
        #if summary == "active":
        #    layout.prop_menu_enum(transform, "uniformity")
    
    context.window_manager.popup_menu(draw_popup_menu, title="{}".format(title))

@addon.Operator(idname="object.batch_transform_reset_vectors", options={'REGISTER', 'UNDO'}, description=
"Click: reset all axes (+Ctrl: respect locks, +Shift: reset all vectors)", space_type='VIEW_3D')
def Operator_Reset_Vectors(self, context, event, vectors=""):
    vectors = (None if UIMonitor.shift else {"_".join(n.split()).lower() for n in vectors.split(",")})
    
    category = get_category()
    transform = category.find_transform(context.screen, context.area)
    
    tfm_mode = transform.get_transform_mode(context.mode)
    if tfm_mode: tfm_mode.reset_vectors(vectors, not UIMonitor.ctrl)
    
    return {'FINISHED'}

class BaseTransformPG:
    vector_names = tuple()
    
    def begin(self, transform, vector_name, axis_name, summary_index, uniformity):
        selfx = addon[self]
        tfm_aggr = getattr(selfx, "tfm_aggr", None)
        if tfm_aggr is None: return # no aggr yet, can't do anything
        
        context = bpy.context
        
        tfm_aggr.store(context)
        
        vector_aggr = getattr(tfm_aggr, "aggr_"+vector_name)
        
        summary = selfx.summaries[summary_index]
        summary_vector = selfx.summary_vectors[summary_index][vector_name]
        vector_prop = getattr(self, vector_name)
        axis_index = vector_prop.axis_names.index(axis_name)
        locks = tuple(getattr(vector_prop, axis_name+"_lock").lock_uniformity for axis_name in vector_prop.axis_names)
        
        if summary == "active":
            object_uniformity = transform.uniformity
            reference_vector = (0.0,) * len(summary_vector)
        elif summary == "min":
            object_uniformity = 'PROPORTIONAL'
            reference_vector = tuple(vector_aggr.get("max", 0.0, False))
        elif summary == "max":
            object_uniformity = 'PROPORTIONAL'
            reference_vector = tuple(vector_aggr.get("min", 0.0, False))
        elif summary == "center":
            object_uniformity = 'OFFSET'
            reference_vector = (0.0,) * len(summary_vector)
        elif summary == "range":
            object_uniformity = 'PROPORTIONAL'
            reference_vector = tuple(vector_aggr.get("center", 0.0, False))
        elif summary == "mean":
            object_uniformity = 'OFFSET'
            reference_vector = (0.0,) * len(summary_vector)
        elif summary == "stddev":
            object_uniformity = 'PROPORTIONAL'
            reference_vector = tuple(vector_aggr.get("mean", 0.0, False))
        elif summary == "median":
            object_uniformity = 'OFFSET'
            reference_vector = (0.0,) * len(summary_vector)
        
        selfx.vector_name = vector_name
        selfx.axis_name = axis_name
        selfx.axis_index = axis_index
        selfx.summary_index = summary_index
        selfx.summary = summary
        selfx.summary_vector = summary_vector
        selfx.vector_prop = vector_prop
        selfx.locks = locks
        selfx.vector_uniformity = uniformity
        selfx.object_uniformity = object_uniformity
        selfx.reference_vector = reference_vector
        
        bpy.ops.ed.undo_push(message="Batch {}.{}".format(vector_name, axis_name))
    
    def modify(self, value):
        selfx = addon[self]
        tfm_aggr = getattr(selfx, "tfm_aggr", None)
        if tfm_aggr is None: return # no aggr yet, can't do anything
        
        context = bpy.context
        
        vector_old = selfx.summary_vector
        vector_ref = selfx.reference_vector
        
        axis_index = selfx.axis_index
        axis_old = vector_old[axis_index]
        axis_ref = vector_ref[axis_index]
        axis_new = value
        axis_delta = axis_new - axis_old
        axis_old_ref = axis_old - axis_ref
        axis_new_ref = axis_new - axis_ref
        axis_scale = (axis_new_ref / axis_old_ref if axis_old_ref != 0.0 else 0.0)
        
        locks = selfx.locks
        vector_uniformity = ('INDEPENDENT' if locks[axis_index] else selfx.vector_uniformity)
        
        if vector_uniformity == 'INDEPENDENT':
            locks = tuple((i != axis_index) for i, lock in enumerate(locks))
        
        if vector_uniformity == 'EQUAL':
            vector_new = tuple((axis_old if locks[i] else axis_new)
                for i, axis_old in enumerate(vector_old))
        elif vector_uniformity == 'OFFSET':
            vector_new = tuple((axis_old if locks[i] else axis_old+axis_delta)
                for i, axis_old in enumerate(vector_old))
        elif vector_uniformity == 'PROPORTIONAL':
            vector_new = tuple((axis_old if locks[i] else vector_ref[i] + axis_scale * (axis_old - vector_ref[i]))
                for i, axis_old in enumerate(vector_old))
        else:
            vector_new = tuple((axis_old if i != axis_index else axis_new)
                for i, axis_old in enumerate(vector_old))
        
        vector_delta = tuple(vector_new[i] - vector_old[i] for i in range(len(vector_old)))
        vector_scale = tuple((vector_new[i] / vector_old[i] if vector_old[i] != 0.0 else 0.0) for i in range(len(vector_old)))
        
        getattr(self, selfx.vector_name).set_vector(selfx.summary_index, vector_new)
        
        tfm_aggr.restore(context, selfx.vector_name, selfx.object_uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)
    
    def modify_lock(self, vector_name, axis_name, value):
        selfx = addon[self]
        tfm_aggr = getattr(selfx, "tfm_aggr", None)
        if tfm_aggr is None: return # no aggr yet, can't do anything
        
        context = bpy.context
        
        vector_prop = getattr(self, vector_name)
        try:
            axis_index = vector_prop.axis_names.index(axis_name)
        except ValueError:
            axis_index = -1
        
        bpy.ops.ed.undo_push(message="Batch {}.{} (un)lock".format(vector_name, axis_name))
        
        tfm_aggr.lock(context, vector_name, axis_index, value)
    
    def modify_prop(self, prop_name, value, avoid_errors=True):
        selfx = addon[self]
        tfm_aggr = getattr(selfx, "tfm_aggr", None)
        if tfm_aggr is None: return # no aggr yet, can't do anything
        
        context = bpy.context
        
        bpy.ops.ed.undo_push(message="Batch set {}".format(prop_name))
        
        tfm_aggr.set_prop(context, prop_name, value, avoid_errors)
    
    def apply(self, tfm_aggr, summaries):
        selfx = addon[self]
        selfx.tfm_aggr = tfm_aggr
        selfx.summaries = summaries
        selfx.summary_vectors = []
        
        for vector_name in self.vector_names:
            getattr(self, vector_name).match_summaries(summaries)
        
        for i, summary in enumerate(summaries):
            vectors = {}
            for vector_name in self.vector_names:
                if summary == 'active':
                    vector = getattr(tfm_aggr, vector_name)
                else:
                    vector_aggr = getattr(tfm_aggr, "aggr_"+vector_name)
                    vector = vector_aggr.get(summary, 0.0, False)
                
                getattr(self, vector_name).set_vector(i, vector)
                vectors[vector_name] = vector
            
            selfx.summary_vectors.append(vectors)
        
        for vector_name in self.vector_names:
            aggr_name = "aggr_"+vector_name
            vector_prop = getattr(self, vector_name)
            vector_prop["vector:same"] = getattr(tfm_aggr, aggr_name).same
            
            aggr_lock_name = aggr_name+"_lock"
            if hasattr(tfm_aggr, aggr_lock_name):
                lock_aggr = getattr(tfm_aggr, aggr_lock_name)
                vector_prop.lock_transformation = lock_aggr.get("mean", False, False)
                vector_prop["lock:same"] = lock_aggr.same
        
        self.apply_special_cases(tfm_aggr)
    
    def apply_special_cases(self, tfm_aggr):
        pass
    
    def draw(self, layout, summaries):
        self.draw_special_cases_pre(layout)
        for vector_name in self.vector_names:
            getattr(self, vector_name).draw(layout, summaries)
        self.draw_special_cases_post(layout)
    
    def draw_special_cases_pre(self, layout):
        pass
    
    def draw_special_cases_post(self, layout):
        pass
    
    def reset_vectors(self, vector_names=None, ignore_locks=True):
        selfx = addon[self]
        tfm_aggr = getattr(selfx, "tfm_aggr", None)
        if tfm_aggr is None: return # no aggr yet, can't do anything
        
        for vector_name in self.vector_names:
            if (vector_names is not None) and (vector_name not in vector_names): continue
            
            vector_prop = getattr(self, vector_name)
            if not vector_prop.resetable: continue
            
            if ignore_locks:
                locks = tuple(False for axis_name in vector_prop.axis_names)
            else:
                locks = tuple(getattr(vector_prop, axis_name+"_lock").lock_uniformity for axis_name in vector_prop.axis_names)
            
            context = bpy.context
            object_uniformity = 'EQUAL'
            
            vector_new = vector_prop.axis_defaults
            vector_delta = (0.0,) * len(vector_new)
            vector_scale = (1.0,) * len(vector_new)
            vector_ref = (0.0,) * len(vector_new)
            
            tfm_aggr.store(context)
            tfm_aggr.restore(context, vector_name, object_uniformity, vector_new, vector_delta, vector_scale, vector_ref, locks)

# Note: bpy properties only work when declared in the actually registered class, so I have to use mixins.
class BaseLRSTransformPG(BaseTransformPG):
    vector_names = ("location", "rotation", "scale")
    
    location = SummaryVectorPG("Location", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
    ], extra_operators=[({"operator":"object.transform_apply", "text":"Apply"}, {"location":True})]) | prop()
    rotation = SummaryVectorPG("Rotation", [
        ("w", 0.0, None, [dict(subtype='NONE'), dict(name="\u03B1", subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
        ("x", 0.0, False, [dict(subtype='NONE'), dict(subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
        ("y", 0.0, False, [dict(subtype='NONE'), dict(subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
        ("z", 0.0, False, [dict(subtype='NONE'), dict(subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
    ], True, extra_operators=[({"operator":"object.transform_apply", "text":"Apply"}, {"rotation":True})]) | prop()
    scale = SummaryVectorPG("Scale", [
        ("x", 1.0, False, [dict(subtype='NONE')], dict(precision=3)),
        ("y", 1.0, False, [dict(subtype='NONE')], dict(precision=3)),
        ("z", 1.0, False, [dict(subtype='NONE')], dict(precision=3)),
    ], extra_operators=[({"operator":"object.transform_apply", "text":"Apply"}, {"scale":True})]) | prop()
    
    def apply_special_cases(self, tfm_aggr):
        setattr_cmp(self.rotation.w4d_lock, "lock_4d", tfm_aggr.aggr_rotation_lock_4d.get("mean", False))
        self.rotation["w4d_lock:same"] = tfm_aggr.aggr_rotation_lock_4d.same
        
        setattr_cmp(self.rotation.mode, "mode", tfm_aggr.aggr_rotation_mode.get("mode", 'XYZ'))
        self.rotation["mode:same"] = tfm_aggr.aggr_rotation_mode.same

class BaseLRSDTransformPG(BaseLRSTransformPG):
    vector_names = ("location", "rotation", "scale", "dimensions")
    dimensions = SummaryVectorPG("Dimensions", [
        ("x", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
        ("y", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
        ("z", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
    ], resetable=False) | prop()

@addon.PropertyGroup(mixins=BaseLRSDTransformPG)
class ObjectTransformPG:
    pass

@addon.PropertyGroup(mixins=BaseTransformPG)
class MeshTransformPG:
    vector_names = ("location", "bevel", "subsurf")
    
    location = SummaryVectorPG("Location", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
    ]) | prop()
    bevel = SummaryVectorPG("Bevel", [
        ("Vertices", 0.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=1)),
        ("Edges", 0.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=1)),
    ]) | prop()
    subsurf = SummaryVectorPG("SubSurf", [
        ("Crease", 0.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=1)),
    ]) | prop()

@addon.PropertyGroup(mixins=BaseTransformPG)
class CurveTransformPG:
    vector_names = ("location", "weight", "radius", "tilt")
    
    location = SummaryVectorPG("Location", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("w", 0.0, False, [dict(subtype='NONE')], dict(precision=3, min=0)),
    ]) | prop()
    weight = SummaryVectorPG("Weight", [
        ("Weight", 1.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=1, description="Softbody goal weight")),
    ]) | prop()
    radius = SummaryVectorPG("Radius", [
        ("Radius", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0, description="Radius for beveling")),
    ]) | prop()
    tilt = SummaryVectorPG("Tilt", [
        ("Tilt", 0.0, False, [dict(subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
    ]) | prop()

@addon.PropertyGroup(mixins=BaseLRSTransformPG)
class MetaTransformPG:
    vector_names = ("location", "rotation", "dimensions", "radius", "stiffness")
    
    radius = SummaryVectorPG("Radius", [
        ("Radius", 2.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
    ]) | prop()
    stiffness = SummaryVectorPG("Stiffness", [
        ("Stiffness", 2.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=10)),
    ]) | prop()
    dimensions = SummaryVectorPG("Size", [
        ("x", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
        ("y", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
        ("z", 1.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3, min=0)),
    ]) | prop()
    
    is_ellipsoid_base = True | prop()
    def _get(self):
        return self.is_ellipsoid_base
    def _set(self, value):
        self.modify_prop("is_ellipsoid", value)
    is_ellipsoid = True | prop("Type of metaelement (ellipsoid or cuboid)", get=_get, set=_set)
    
    is_negative_base = False | prop()
    def _get(self):
        return self.is_negative_base
    def _set(self, value):
        self.modify_prop("is_negative", value)
    is_negative = False | prop("Sign of metaelement (additive or subtractive)", get=_get, set=_set)
    
    def draw_special_cases_pre(self, layout):
        with layout.row(True):
            with layout.row(True)(alert=not self.get("is_ellipsoid:same", True)):
                layout.prop(self, "is_ellipsoid", text="Ellipsoid")
            with layout.row(True)(alert=not self.get("is_negative:same", True)):
                layout.prop(self, "is_negative", text="Negative")
    
    def apply_special_cases(self, tfm_aggr):
        BaseLRSTransformPG.apply_special_cases(self, tfm_aggr)
        
        setattr_cmp(self, "is_ellipsoid_base", tfm_aggr.aggr_is_ellipsoid.get("mean", True))
        self["is_ellipsoid:same"] = tfm_aggr.aggr_is_ellipsoid.same
        
        setattr_cmp(self, "is_negative_base", tfm_aggr.aggr_is_negative.get("mean", False))
        self["is_negative:same"] = tfm_aggr.aggr_is_negative.same

@addon.PropertyGroup(mixins=BaseTransformPG)
class LatticeTransformPG:
    vector_names = ("location", "weight")
    
    location = SummaryVectorPG("Location", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=5)),
    ]) | prop()
    weight = SummaryVectorPG("Weight", [
        ("Weight", 0.0, False, [dict(subtype='NONE')], dict(precision=3, min=0, max=1, description="Softbody goal weight")),
    ]) | prop()

@addon.PropertyGroup(mixins=BaseLRSTransformPG)
class PoseTransformPG:
    pass

@addon.PropertyGroup(mixins=BaseTransformPG)
class BoneTransformPG:
    vector_names = ("head", "tail", "roll", "envelope")
    
    head = SummaryVectorPG("Head", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
    ]) | prop()
    tail = SummaryVectorPG("Tail", [
        ("x", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("y", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("z", 0.0, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
    ]) | prop()
    roll = SummaryVectorPG("Roll", [
        ("Roll", 0.0, False, [dict(subtype='ANGLE', unit='ROTATION')], dict(precision=3)),
    ]) | prop()
    envelope = SummaryVectorPG("Envelope", [
        ("Head", 0.1, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("Tail", 0.1, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("Distance", 0.25, False, [dict(subtype='DISTANCE', unit='LENGTH')], dict(precision=3)),
        ("Weight", 1.0, None, [dict(subtype='NONE')], dict(precision=3)),
    ]) | prop()

@addon.PropertyGroup(mixins=BaseTransformPG) # TODO?
class GreaseTransformPG:
    pass

@addon.Operator(idname="object.batch_transform_summary", options={'INTERNAL'}, description=
"Click: Summary menu")
def Operator_Summary(self, context, event, index=0, summary="", title=""):
    category = get_category()
    options = get_options()
    
    def draw_popup_menu(self, context):
        layout = NestedLayout(self.layout)
        
        transform = category.transforms[index]
        
        layout.operator("object.batch_transform_summary_copy", text="Copy", icon='COPYDOWN')
        layout.operator("object.batch_transform_summary_paste", text="Paste", icon='PASTEDOWN')
        layout.operator("object.batch_transform_summary_paste", text="+ Paste", icon='PASTEDOWN')
        layout.operator("object.batch_transform_summary_paste", text=" \u2013 Paste", icon='PASTEDOWN')
        layout.operator("object.batch_transform_summary_paste", text=" * Paste", icon='PASTEDOWN')
        layout.operator("object.batch_transform_summary_paste", text="\u00F7 Paste", icon='PASTEDOWN')
        
        #if summary == "active":
        #    layout.prop_menu_enum(transform, "uniformity")
    
    context.window_manager.popup_menu(draw_popup_menu, title="{}".format(title))

@addon.Operator(idname="object.batch_transform_summary_copy", options={'INTERNAL'}, description=
"Click: Copy")
def Operator_Summary_Copy(self, context, event):
    category = get_category()
    options = get_options()

@addon.Operator(idname="object.batch_transform_summary_paste", options={'INTERNAL'}, description=
"Click: Paste")
def Operator_Summary_Paste(self, context, event):
    category = get_category()
    options = get_options()

@addon.Operator(idname="object.batch_transform_property", options={'INTERNAL'}, description=
"Click: Property menu")
def Operator_Property(self, context, event, property_name=""):
    category = get_category()
    options = get_options()

# Should probably be stored in each Screen?
@addon.PropertyGroup
class ContextTransformPG:
    # Currently Blender doesn't support user-defined properties
    # for SpaceView3D -> we have to maintain a separate mapping.
    is_v3d = False | prop()
    index = 0 | prop()
    
    @property
    def ui_context(self):
        selfx = addon[self]
        
        area = getattr(selfx, "area", None)
        if (not area) or (not area.regions): return {}
        
        space_data = area.spaces.active
        if space_data.type != 'VIEW_3D': return {}
        
        region = getattr(selfx, "region", None)
        if not region:
            for _region in area.regions:
                if _region.type == 'WINDOW': region = _region
        region_data = getattr(selfx, "region_data", None) or rv3d_from_region(area, region)
        
        window = getattr(selfx, "window", None) or bpy.context.window
        screen = getattr(selfx, "screen", None) or bpy.context.screen
        
        return dict(window=window, screen=screen,
            area=area, space_data=space_data,
            region=region, region_data=region_data)
    
    # Summaries are stored here because they might be different for each 3D view
    summary_items = [
        ('active', "Active", "", 'ROTACTIVE'),
        ('min', "Min", "", 'MOVE_DOWN_VEC'),
        ('max', "Max", "", 'MOVE_UP_VEC'),
        ('center', "Center", "", 'ROTATE'),
        ('range', "Range", "", 'STICKY_UVS_VERT'),
        ('mean', "Mean", "", 'ROTATECENTER'),
        ('stddev', "StdDev", "", 'SMOOTHCURVE'),
        ('median', "Median", "", 'SORTSIZE'),
        #('mode', "Mode", "", 'GROUP_VERTEX'),
    ]
    summaries = {'mean'} | prop("Summaries", items=summary_items)
    
    # This affects only the "active" summary, since all others
    # are mostly applicable only in one way
    uniformity_items = [
        ('EQUAL', "Equal", "", 'COLLAPSEMENU'), # COLLAPSEMENU LINKED
        ('OFFSET', "Offset", "", 'ZOOMIN'), # PLUS
        ('PROPORTIONAL', "Proportional", "", 'FULLSCREEN_ENTER'), # X CURVE_PATH
    ]
    uniformity_icons = {item[0]:item[3] for item in uniformity_items}
    uniformity = 'OFFSET' | prop("Batch modification", items=uniformity_items)
    
    use_pinned_coordsystem = False | prop()
    coordsystem_selector = CoordSystemPG | prop() # IDBlock selector
    
    @property
    def coordsystem(self):
        manager = get_coordsystem_manager(bpy.context)
        return manager.coordsystems.get(self.coordsystem_selector.selector)
    
    def draw_coordsystem_selector(self, layout):
        manager = get_coordsystem_manager(bpy.context)
        if not self.coordsystem_selector.is_bound:
            self.coordsystem_selector.bind(manager.coordsystems, rename=False)
        
        with layout.row(True):
            icon = ('PINNED' if self.use_pinned_coordsystem else 'UNPINNED')
            layout.prop(self, "use_pinned_coordsystem", text="", icon=icon, toggle=True)
            if self.use_pinned_coordsystem:
                self.coordsystem_selector.draw(layout)
            else:
                setattr_cmp(self.coordsystem_selector, "selector", manager.coordsystem.selector)
                with layout.row(True)(enabled=False):
                    self.coordsystem_selector.draw(layout)
    
    object = ObjectTransformPG | prop()
    mesh = MeshTransformPG | prop()
    curve = CurveTransformPG | prop()
    meta = MetaTransformPG | prop()
    lattice = LatticeTransformPG | prop()
    pose = PoseTransformPG | prop()
    bone = BoneTransformPG | prop()
    
    # Since Blender 2.73, grease pencil data is editable too
    grease = GreaseTransformPG | prop() # TODO?
    
    _mode_map = {'OBJECT':"object", 'POSE':"pose", 'EDIT_MESH':"mesh", 'EDIT_CURVE':"curve",
        'EDIT_SURFACE':"curve", 'EDIT_ARMATURE':"bone", 'EDIT_METABALL':"meta", 'EDIT_LATTICE':"lattice"}
    def get_transform_mode(self, mode):
        mode = self._mode_map.get(mode)
        return (getattr(self, mode) if mode else None)
    
    def apply(self, tfm_aggr):
        summaries = [item[0] for item in self.summary_items if item[0] in self.summaries]
        tfm_mode = self.get_transform_mode(tfm_aggr.mode)
        if tfm_mode: tfm_mode.apply(tfm_aggr, summaries)
    
    def draw(self, layout):
        self.draw_coordsystem_selector(layout)
        
        with layout.row(True):
            for item in self.summary_items:
                if item[0] in self.summaries:
                    text = item[1]
                    if item[0] == 'active':
                        if self.uniformity == 'OFFSET': text = "+" + text
                        elif self.uniformity == 'PROPORTIONAL': text = "* " + text
                    op = layout.operator("object.batch_transform_summary", text=text)
                    op.index = self.index
                    op.summary = item[0]
                    op.title = item[1]
            
            if not self.summaries: layout.label(" ") # just to fill space
            
            with layout.row(True)(scale_x=1.0): # scale_x to prevent up/down arrows from appearing
                layout.prop_menu_enum(self, "summaries", text="", icon='DOTSDOWN')
        
        tfm_mode = self.get_transform_mode(bpy.context.mode)
        if tfm_mode: tfm_mode.draw(layout, self.summaries)

@addon.PropertyGroup
class CategoryPG:
    transforms = [ContextTransformPG] | prop()
    
    selection_info = None
    
    def find_transform(self, screen, area):
        areas = screen.areas
        transforms = self.transforms
        is_v3d = (area.type == 'VIEW_3D')
        
        found = False
        searches = 2 # just to be sure there won't be an infinite loop
        while searches > 0:
            for i in range(len(areas)):
                if areas[i] != area: continue
                if i >= len(transforms): break
                transform = transforms[i]
                if transform.is_v3d != is_v3d: break
                transformExt = addon[transform]
                if not hasattr(transformExt, "area"): break
                if transformExt.area != area: break
                found = True
            if not found: self.transforms_ensure_order(screen)
            searches -= 1
        
        return (transform if found else None)
    
    def transforms_ensure_order(self, screen):
        areas = screen.areas
        transforms = self.transforms
        
        for i in range(len(areas)):
            area = areas[i]
            is_v3d = (area.type == 'VIEW_3D')
            
            while i < len(transforms):
                transform = transforms[i]
                transformExt = addon[transform]
                if not hasattr(transformExt, "area"):
                    transformExt.area = area # happens when .blend was loaded
                    break # (supposedly saved/loaded in the correct order)
                elif transformExt.area.regions:
                    break # area is valid
                transforms.remove(i) # remove invalid area's transform
            else:
                transform = transforms.add()
                transformExt = addon[transform]
                transformExt.area = area
            
            if transformExt.area != area:
                for j in range(i, len(transforms)):
                    transform = transforms[i]
                    transformExt = addon[transform]
                    if transformExt.area == area: break
                else: # not found
                    transform = transforms.add()
                    transformExt = addon[transform]
                    transformExt.area = area
                    j = len(transforms) - 1
                transform.is_v3d = is_v3d
                transform.index = i
                transforms.move(j, i)
            else:
                transform.is_v3d = is_v3d
                transform.index = i
        
        for i in range(len(transforms)-1, len(areas)-1, -1):
            transforms.remove(i) # remove extra transforms
    
    def draw(self, layout, context):
        layout = NestedLayout(layout, addon.module_name+".transform")
        
        transform = self.find_transform(context.screen, context.area)
        transform.draw(layout)

@addon.Operator(idname="view3d.pick_transforms", options={'INTERNAL', 'REGISTER'}, description=
"Pick transform(s) from the object under mouse")
class Operator_Pick(Pick_Base):
    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT')
    
    def obj_to_info(self, obj):
        L, R, S = obj.matrix_world.decompose()
        L = "{:.5f}, {:.5f}, {:.5f}".format(*tuple(L))
        R = "{:.3f}, {:.3f}, {:.3f}".format(*tuple(math.degrees(axis) for axis in R.to_euler()))
        S = "{:.3f}, {:.3f}, {:.3f}".format(*tuple(S))
        return "Location: {}, Rotation: {}, Scale: {}".format(L, R, S)
    
    def on_confirm(self, context, obj):
        category = get_category()
        options = get_options()
        bpy.ops.ed.undo_push(message="Pick Transforms")
        #BatchOperations.copy(obj)
        self.report({'INFO'}, "Transforms copied")
        #BatchOperations.paste(options.iterate_objects(context), options.paste_mode)

# NOTE: only when 'REGISTER' is in bl_options and {'FINISHED'} is returned,
# the operator will be recorded in wm.operators and info reports

@addon.Operator(idname="object.batch_transform_copy", options={'INTERNAL'}, description=
"Click: Copy")
def Operator_Copy(self, context, event, object_name=""):
    active_obj = (bpy.data.objects.get(object_name) if object_name else context.object)
    if not active_obj: return
    category = get_category()
    options = get_options()
    # TODO ?

@addon.Operator(idname="object.batch_transform_paste", options={'INTERNAL', 'REGISTER'}, description=
"Click: Paste (+Ctrl: Override, +Shift: Add, +Alt: Filter)")
def Operator_Paste(self, context, event):
    category = get_category()
    options = get_options()
    # TODO ?
    return {'FINISHED'}

@addon.PropertyGroup
class CategoryOptionsPG:
    sync_3d_views = True | prop("Synchronize between 3D views")

@addon.Menu(idname="VIEW3D_MT_batch_transforms_options", label="Options", description="Options")
def Menu_Options(self, context):
    layout = NestedLayout(self.layout)
    options = get_options()
    layout.prop(options, "sync_3d_views", text="Sync 3D views")
    layout.label("Apply pos/rot/scale") # TODO
    layout.label("Set geometry origin") # TODO

@LeftRightPanel(idname="VIEW3D_PT_batch_transforms", space_type='VIEW_3D', category="Transform", label="Batch Transforms")
class Panel_Category:
    #def draw_header(self, context):
    #    layout = NestedLayout(self.layout)
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        category = get_category()
        options = get_options()
        transform = category.find_transform(context.screen, context.area)
        
        with layout.row():
            with layout.row(True):
                layout.operator("view3d.pick_transforms", icon='EYEDROPPER', text="")
                layout.operator("object.batch_transform_copy", icon='COPYDOWN', text="")
                layout.operator("object.batch_transform_paste", icon='PASTEDOWN', text="")
            
            layout.operator("wm.finish_selection_analysis", icon='FILE_REFRESH', text="")
            
            icon = transform.uniformity_icons[transform.uniformity]
            layout.prop_menu_enum(transform, "uniformity", text="", icon=icon)
            
            icon = 'SCRIPTWIN'
            layout.menu("VIEW3D_MT_batch_transforms_options", icon=icon, text="")
        
        category.draw(layout, context)

addon.type_extend("Screen", "batch_transforms", CategoryPG)
def get_category(context=None):
    if context is None: context = bpy.context
    return context.screen.batch_transforms

setattr(addon.Preferences, "transforms", CategoryOptionsPG | prop())
get_options = (lambda: addon.preferences.transforms)
