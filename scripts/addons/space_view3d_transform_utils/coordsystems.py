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

addon = AddonManager()

#============================================================================#

# =========================================================================== #
#                               < COORDSYSTEMS >                              #
# =========================================================================== #

class CoordSystemMatrix:
    def __init__(self, coordsys=None, sv=None, context=None):
        self.update(coordsys, sv, context)
    
    def __coordsys_get(self, coordsys, aspect):
        aspect = coordsys.get(aspect)
        if aspect is None: return ('GLOBAL', "", "")
        elif isinstance(aspect, str): return (aspect, "", "")
        elif len(aspect) == 1: return (aspect[0], "", "")
        elif len(aspect) == 2: return (aspect[0], aspect[1], "")
        else: return (aspect[0], aspect[1], aspect[2])
    def _interpret_coordsys_dict(self, coordsys):
        self.L = self.__coordsys_get(coordsys, "L")
        self.R = self.__coordsys_get(coordsys, "R")
        self.S = self.__coordsys_get(coordsys, "S")
        self.extra_matrix = coordsys.get("extra_matrix") or Matrix()
    def _interpret_coordsys_pg(self, coordsys):
        aspect = coordsys.aspect_L
        self.L = (aspect.mode, aspect.obj_name, aspect.bone_name)
        aspect = coordsys.aspect_R
        self.R = (aspect.mode, aspect.obj_name, aspect.bone_name)
        aspect = coordsys.aspect_S
        self.S = (aspect.mode, aspect.obj_name, aspect.bone_name)
        self.extra_matrix = coordsys.extra_matrix
    def _interpret_coordsys_str(self, L='GLOBAL', R='GLOBAL', S='GLOBAL'):
        self.L = (L, "", "")
        self.R = (R, "", "")
        self.S = (S, "", "")
        self.extra_matrix = Matrix()
    def _interpret_coordsys(self, coordsys, context):
        if isinstance(coordsys, dict):
            self._interpret_coordsys_dict(coordsys)
        elif isinstance(coordsys, str):
            if coordsys == 'NORMAL':
                self._interpret_coordsys_str('MEAN', 'NORMAL')
            elif coordsys == 'MANIPULATOR':
                self._interpret_coordsys_str('PIVOT', 'ORIENTATION')
            elif coordsys == 'CURRENT':
                if context is None: context = bpy.context
                manager = get_coordsystem_manager(context)
                self._interpret_coordsys(manager.current, context)
            else:
                self._interpret_coordsys_str(coordsys, coordsys, coordsys)
        elif coordsys: # CoordSystemPG
            self._interpret_coordsys_pg(coordsys)
        else:
            self._interpret_coordsys_str()
    
    def update(self, coordsys, sv=None, context=None):
        self._interpret_coordsys(coordsys, context)
        
        self.context = context
        
        self.calc_active_xyzt(context)
        
        if (sv is None) and context:
            ui_context = self.find_ui_context(context)
            if ui_context: sv = SmartView3D(use_camera_axes=True, **ui_context)
        
        self.sv = sv
        self.vm, self.vp = self.calc_view_matrix()
        
        # Cached values are the same for any object/element
        self._cached_all = None
        self._cached_t = None
        self._cached_xyz = None
        self._cached_s = None
    
    # The "basis" location/rotation/scale can be used with objects and pose-bones
    # (they have the same the transform-related attributes, even locks!)
    # Meta-elements have pos/rot/scale too, but nothing more advanced.
    # However, meta-elements can also be coerced to the same behavior, to some extent
    
    def calc_view_matrix(self):
        if not self.sv: return (Matrix(), Vector((1,1,0)))
        m = matrix_compose(self.sv.right, self.sv.up, self.sv.forward, self.sv.viewpoint)
        m3 = m.to_3x3()
        s, d = self.sv.projection_info
        p = Vector((2.0/s.x, 2.0/s.y, s.z)).lerp(Vector((2.0*d.z/s.x, 2.0*d.z/s.y, s.z)), s.z)
        x = m3 * Vector((1, 0, 0))
        y = m3 * Vector((0, 1, 0))
        z = m3 * Vector((d.x, d.y, 1.0)).lerp(Vector((d.x/d.z, d.y/d.z, 1.0)), s.z)
        t = m.translation
        return (matrix_compose(x, y, -z, t), p)
    
    def calc_cam_matrix(self, context, cam_name):
        scene = context.scene
        cam_obj = scene.objects.get(cam_name, scene.camera)
        if (not cam_obj) or (not cam_obj.data): return (Matrix(), Vector((1,1,0)))
        m = Matrix(cam_obj.matrix_world)
        m.col[0] *= (1.0 / m.col[0].magnitude)
        m.col[1] *= (1.0 / m.col[1].magnitude)
        m.col[2] *= -(1.0 / m.col[2].magnitude)
        m3 = m.to_3x3()
        s, d = BlUtil.Camera.projection_info(cam_obj.data, context.scene)
        p = Vector((2.0/s.x, 2.0/s.y, s.z)).lerp(Vector((2.0*d.z/s.x, 2.0*d.z/s.y, s.z)), s.z)
        x = m3 * Vector((1, 0, 0))
        y = m3 * Vector((0, 1, 0))
        z = m3 * Vector((d.x, d.y, 1.0)).lerp(Vector((d.x/d.z, d.y/d.z, 1.0)), s.z)
        t = m.translation
        return (matrix_compose(x, y, -z, t), p)
    
    def calc_active_matrix(self, context):
        if context.mode == 'EDIT_METABALL':
            elem = context.active_object.data.elements.active
            return BlUtil.Object.matrix_world(ObjectEmulator_Meta(elem))
        elif context.mode == 'POSE':
            return BlUtil.Object.matrix_world(context.active_pose_bone)
        else:
            return BlUtil.Object.matrix_world(context.active_object)
    
    def _xyzt_t(self, m, xyzt):
        if (xyzt is None) or (xyzt[3] is None):
            t = m.translation
        else:
            t = m * Vector(xyzt[3])
        return t
    
    def _xyzt_xyz(self, m, xyzt):
        if xyzt is None:
            xyz = m.col[:3]
        else:
            x, y, z = xyzt[0], xyzt[1], xyzt[2]
            if (x is None) and (y is None) and (z is None):
                xyz = m.col[:3]
            else:
                m3 = m.to_3x3()
                if x is not None: x = m3 * Vector(x)
                if y is not None: y = m3 * Vector(y)
                if z is not None: z = m3 * Vector(z)
                xyz = orthogonal_XYZ(x, y, z, "z")
        return xyz
    
    def _xyzt_s(self, m, xyzt):
        if xyzt is None:
            s = m.to_scale()
        else:
            s = Vector((1,1,1))
        return s
    
    def _gimbal_xyz(self, context, am):
        rotobj = (context.active_pose_bone if context.mode == 'POSE' else None) or context.active_object
        
        if (not rotobj) or (rotobj.rotation_mode == 'QUATERNION'):
            if not am: am = self.calc_active_matrix(context)
            xyz = am.col[:3]
        elif rotobj.rotation_mode == 'AXIS_ANGLE':
            aa = rotobj.rotation_axis_angle
            z = Vector(aa[1:]).normalized()
            q = Vector((0,0,1)).rotation_difference(z)
            x = (q * Vector((1,0,0))).normalized()
            y = z.cross(x)
        else:
            e = rotobj.rotation_euler
            m = Matrix.Identity(3)
            for e_ax in rotobj.rotation_mode:
                m = Matrix.Rotation(getattr(e, e_ax.lower()), 3, e_ax) * m
            x, y, z = m.col[:3]
        
        if not xyz:
            m = BlUtil.Object.matrix_parent(rotobj)
            x.rotate(m)
            y.rotate(m)
            z.rotate(m)
            xyz = x, y, z
        
        return xyz
    
    # The actual implementations are substituted other modules
    get_coord_summary = staticmethod(lambda summary, dflt: Vector.Fill(3, dflt))
    get_normal_summary = staticmethod(lambda summary: Vector((0,0,1)))
    find_ui_context = staticmethod(lambda context: None)
    workplane_matrix = staticmethod(lambda context, scaled: Matrix())
    
    _pivot_map = {
        'BOUNDING_BOX_CENTER':'CENTER',
        'CURSOR':'CURSOR',
        'INDIVIDUAL_ORIGINS':'INDIVIDUAL',
        'MEDIAN_POINT':'MEAN',
        'ACTIVE_ELEMENT':'ACTIVE',
    }
    _orientation_map = {
        'GLOBAL':'GLOBAL',
        'LOCAL':'ACTIVE',
        'NORMAL':'NORMAL',
        'GIMBAL':'GIMBAL',
        'VIEW':'VIEW',
    }
    _orientation_map_edit = {
        'GLOBAL':'GLOBAL',
        'LOCAL':'LOCAL',
        'NORMAL':'NORMAL',
        'GIMBAL':'GIMBAL',
        'VIEW':'VIEW',
    }
    def calc_matrix(self, context, obj, local_xyzt=None):
        if self._cached_all: return self._cached_all
        
        persp = Vector((1,1,0))
        pm = None
        lm = None
        am = None
        wplm = None
        
        L_mode = self.L[0]
        # Note: in POSE mode the manipulator is displayed only at the root selected bone, active bone or cursor,
        # and rotation always happens around the base of the root selected bone
        if L_mode == 'PIVOT': L_mode = self._pivot_map[self.sv.space_data.pivot_point]
        t = self._cached_t
        if not t:
            if L_mode == 'LOCAL':
                if self.active_xyzt: # in mesh/curve/lattice/bone edit modes, treat active object as parent
                    if not am: am = self.calc_active_matrix(context)
                    t = am.translation
                    self._cached_t = t
                else:
                    if not pm: pm = BlUtil.Object.matrix_parent(obj)
                    t = pm.translation
            elif L_mode == 'PARENT':
                if not pm: pm = BlUtil.Object.matrix_parent(obj)
                t = pm.translation
            elif L_mode == 'INDIVIDUAL':
                if not lm: lm = BlUtil.Object.matrix_world(obj)
                t = self._xyzt_t(lm, local_xyzt)
            elif L_mode == 'ACTIVE':
                if not am: am = self.calc_active_matrix(context)
                t = self._xyzt_t(am, self.active_xyzt)
                self._cached_t = t
            elif L_mode == 'OBJECT':
                _obj = (context.scene.objects.get(self.L[1]) if self.L[1] else context.active_object)
                om = BlUtil.Object.matrix_world(_obj, self.L[2])
                t = om.translation
                self._cached_t = t
            elif L_mode == 'CAMERA':
                cm, persp = self.calc_cam_matrix(context, self.L[1])
                t = cm.translation
                self._cached_t = t
            elif L_mode == 'VIEW':
                vm, persp = self.vm, self.vp
                t = vm.translation
                self._cached_t = t
            elif L_mode == 'WORKPLANE':
                if not wplm: wplm = self.workplane_matrix(context, True)
                t = wplm.translation
                self._cached_t = t
            elif L_mode == 'CURSOR':
                t = Vector((self.sv.space_data if self.sv else context.scene).cursor_location)
                self._cached_t = t
            elif L_mode in ('MEAN', 'CENTER', 'MIN', 'MAX'):
                t = self.get_coord_summary(L_mode.lower(), 0.0)
                self._cached_t = t
            else: # GLOBAL, and fallback for some others
                t = Vector()
                self._cached_t = t
        
        S_mode = self.S[0]
        s = self._cached_s
        if not s:
            if S_mode == 'LOCAL':
                if self.active_xyzt: # in mesh/curve/lattice/bone edit modes, treat active object as parent
                    if not am: am = self.calc_active_matrix(context)
                    s = am.to_scale()
                    self._cached_s = s
                else:
                    if not pm: pm = BlUtil.Object.matrix_parent(obj)
                    s = pm.to_scale()
            elif S_mode == 'PARENT':
                if not pm: pm = BlUtil.Object.matrix_parent(obj)
                s = pm.to_scale()
            elif S_mode == 'INDIVIDUAL':
                if not lm: lm = BlUtil.Object.matrix_world(obj)
                s = self._xyzt_s(lm, local_xyzt)
            elif S_mode == 'ACTIVE':
                if not am: am = self.calc_active_matrix(context)
                s = self._xyzt_s(am, self.active_xyzt)
                self._cached_s = s
            elif S_mode == 'OBJECT':
                _obj = (context.scene.objects.get(self.S[1]) if self.S[1] else context.active_object)
                om = BlUtil.Object.matrix_world(_obj, self.S[2])
                s = om.to_scale()
                self._cached_s = s
            elif S_mode == 'CAMERA':
                cm = self.calc_cam_matrix(context, self.S[1])[0]
                s = cm.to_scale()
                self._cached_s = s
            elif S_mode == 'VIEW':
                vm = self.vm
                s = vm.to_scale()
                self._cached_s = s
            elif S_mode == 'WORKPLANE':
                if not wplm: wplm = self.workplane_matrix(context, True)
                s = wplm.to_scale()
                self._cached_s = s
            elif S_mode in ('RANGE', 'STDDEV'):
                s = self.get_coord_summary(S_mode.lower(), 1.0)
                self._cached_s = s
            else: # GLOBAL, and fallback for some others
                s = Vector((1,1,1))
                self._cached_s = s
        
        # R is calculated after S for slight convenience of calculating Gimbal
        R_mode = self.R[0]
        if R_mode == 'ORIENTATION':
            v3d = self.sv.space_data
            ormap = (self._orientation_map_edit if context.mode.startswith('EDIT') else self._orientation_map)
            if not v3d.current_orientation: R_mode = ormap.get(v3d.transform_orientation, v3d.transform_orientation)
        xyz = self._cached_xyz
        if not xyz:
            if R_mode == 'LOCAL':
                if self.active_xyzt: # in mesh/curve/lattice/bone edit modes, treat active object as parent
                    if not am: am = self.calc_active_matrix(context)
                    xyz = am.col[:3]
                    self._cached_xyz = xyz
                else:
                    if not pm: pm = BlUtil.Object.matrix_parent(obj)
                    xyz = pm.col[:3]
            elif R_mode == 'PARENT':
                if not pm: pm = BlUtil.Object.matrix_parent(obj)
                xyz = pm.col[:3]
            elif R_mode == 'INDIVIDUAL':
                if not lm: lm = BlUtil.Object.matrix_world(obj)
                xyz = self._xyzt_xyz(lm, local_xyzt)
            elif R_mode == 'ACTIVE':
                if not am: am = self.calc_active_matrix(context)
                xyz = self._xyzt_xyz(am, self.active_xyzt)
                self._cached_xyz = xyz
            elif R_mode == 'OBJECT':
                _obj = (context.scene.objects.get(self.R[1]) if self.R[1] else context.active_object)
                om = BlUtil.Object.matrix_world(_obj, self.R[2])
                xyz = om.col[:3]
                self._cached_xyz = xyz
            elif R_mode == 'CAMERA':
                cm = self.calc_cam_matrix(context, self.R[1])[0]
                xyz = cm.col[:3]
                self._cached_xyz = xyz
            elif R_mode == 'VIEW':
                vm = self.vm
                xyz = vm.col[:3]
                self._cached_xyz = xyz
            elif R_mode == 'WORKPLANE':
                if not wplm: wplm = self.workplane_matrix(context, True)
                xyz = wplm.col[:3]
                self._cached_xyz = xyz
            elif R_mode == 'NORMAL':
                nm = self.get_normal_summary("mean")
                xyz = nm.col[:3]
                self._cached_xyz = xyz
            elif R_mode == 'GIMBAL':
                xyz = self._gimbal_xyz(context, am)
                self._cached_xyz = xyz
            elif R_mode == 'ORIENTATION':
                v3d = self.sv.space_data
                m = v3d.current_orientation.matrix
                xyz = m.col[:3]
                self._cached_xyz = xyz
            else: # GLOBAL, and fallback for some others
                xyz = Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1))
                self._cached_xyz = xyz
        
        x = s.x * xyz[0].to_3d().normalized()
        y = s.y * xyz[1].to_3d().normalized()
        z = s.z * xyz[2].to_3d().normalized()
        self.__base_matrix = matrix_compose(x, y, z, t)
        final_matrix = self.__base_matrix * self.extra_matrix
        res = (L_mode, R_mode, S_mode, final_matrix, persp)
        
        if self._cached_t and self._cached_xyz and self._cached_s:
            self._cached_all = res
        
        return res
    
    def base_matrix(self, context=None, obj=None):
        self.calc_matrix(context or self.context, obj)
        return self.__base_matrix
    
    def final_matrix(self, context=None, obj=None):
        L_mode, R_mode, S_mode, to_m, persp = self.calc_matrix(context or self.context, obj)
        return to_m
    
    def get_LRS(self, context, obj, rotation_mode='QUATERNION', rotation4=False):
        L_mode, R_mode, S_mode, to_m, persp = self.calc_matrix(context, obj)
        in_m = matrix_inverted_safe(to_m) * BlUtil.Object.matrix_world(obj)
        
        if L_mode == 'BASIS':
            L = Vector(obj.location)
        elif L_mode == 'INDIVIDUAL':
            L = Vector()
        else:
            L = in_m.translation
            if L_mode in ('CAMERA', 'VIEW'):
                inv_z = ((1.0 / abs(L.z)) if L.z != 0.0 else 1.0)
                L = Vector((L.x * persp.x, L.y * persp.y, -L.z)).lerp(
                    Vector((L.x * inv_z * persp.x, L.y * inv_z * persp.y, -L.z)), persp.z)
        
        if R_mode == 'BASIS':
            R = BlUtil.Object.rotation_convert(obj.rotation_mode, obj.rotation_quaternion,
                obj.rotation_axis_angle, obj.rotation_euler, rotation_mode, rotation4)
        elif R_mode == 'INDIVIDUAL':
            R = BlUtil.Object.rotation_convert('QUATERNION', Quaternion((1,0,0,0)),
                None, None, rotation_mode, rotation4)
        else:
            R = BlUtil.Object.rotation_convert('QUATERNION', in_m.to_quaternion(),
                None, None, rotation_mode, rotation4)
        
        if S_mode == 'BASIS':
            S = Vector(obj.scale)
        elif S_mode == 'INDIVIDUAL':
            S = Vector((1,1,1))
        else:
            S = in_m.to_scale()
        
        return (L, R, S)
    
    def set_LRS(self, context, obj, LRS, rotation_mode='QUATERNION'):
        L, R, S = LRS
        L_mode, R_mode, S_mode, to_m, persp = self.calc_matrix(context, obj)
        
        mL = (L is not None) and (L_mode != 'BASIS')
        mR = (R is not None) and (R_mode != 'BASIS')
        mS = (S is not None) and (S_mode != 'BASIS')
        
        if mL or mR or mS:
            in_m = matrix_inverted_safe(to_m) * BlUtil.Object.matrix_world(obj)
            
            if not mL:
                in_L = in_m.to_translation()
            else:
                L = Vector(L) # make sure it's a Vector
                if L_mode in ('CAMERA', 'VIEW'):
                    L = Vector((L.x / persp.x, L.y / persp.y, -L.z)).lerp(
                        Vector((L.x * L.z / persp.x, L.y * L.z / persp.y, -L.z)), persp.z)
                in_L = L
                L = None
            
            if not mR:
                in_R = in_m.to_quaternion()
                if not R: rotation_mode = obj.rotation_mode
            else:
                if rotation_mode == 'QUATERNION':
                    in_R = Quaternion(R)
                elif rotation_mode == 'AXIS_ANGLE':
                    in_R = Quaternion(R[1:], R[0])
                else:
                    if (len(R) == 4): R = R[1:]
                    in_R = Euler(R).to_quaternion()
                R = None
            
            if not mS:
                in_S = in_m.to_scale()
            else:
                in_S = Vector(S)
                S = None
            
            x, y, z = in_R.normalized().to_matrix().col
            in_m = matrix_compose(x*in_S.x, y*in_S.y, z*in_S.z, in_L)
            BlUtil.Object.matrix_world_set(obj, to_m * in_m)
            
            if (not mL) and (not L): L = Vector(obj.location)
            if (not mR) and (not R): R = BlUtil.Object.rotation_convert(obj.rotation_mode, obj.rotation_quaternion,
                obj.rotation_axis_angle, obj.rotation_euler, rotation_mode)
            if (not mS) and (not S): S = Vector(obj.scale)
        
        if L: obj.location = Vector(L)
        if R: BlUtil.Object.rotation_apply(obj, R, rotation_mode)
        if S: obj.scale = Vector(S)
    
    _last_obj_hash = 0
    _last_obj_matrix = None
    _last_obj_matrix_inv = None
    active_xyzt = None # supposed to be assigned directly by the using code
    
    def calc_active_xyzt(self, context=None):
        if context is None: context = bpy.context
        mode = context.mode
        
        self.active_xyzt = None
        
        if not context.object: return
        
        if mode == 'EDIT_ARMATURE':
            obj = context.object.data.edit_bones.active
            if obj:
                self.active_xyzt = (Vector(obj.x_axis), Vector(obj.y_axis), Vector(obj.z_axis), Vector(obj.head))
            else:
                self.active_xyzt = (Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1)), Vector())
        elif mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(context.object.data)
            history = bm.select_history
            obj = (history[len(history)-1] if history else bm.faces.active)
            if obj:
                if isinstance(obj, bmesh.types.BMVert):
                    co = Vector(obj.co)
                    normal = Vector(obj.normal)
                    self.active_xyzt = (None, None, normal, co)
                elif isinstance(obj, bmesh.types.BMEdge):
                    verts = tuple(obj.verts)
                    co0 = Vector(verts[0].co)
                    co1 = Vector(verts[1].co)
                    self.active_xyzt = (None, None, (co1 - co0)*0.5, (co1 + co0)*0.5)
                elif isinstance(obj, bmesh.types.BMFace):
                    verts = tuple(obj.verts)
                    center = sum((Vector(v.co) for v in verts), Vector()) * (1.0 / len(verts))
                    normal = Vector(obj.normal)
                    self.active_xyzt = (None, None, normal, center)
            else:
                self.active_xyzt = (Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1)), Vector())
        elif mode == 'EDIT_LATTICE':
            self.active_xyzt = (Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1)), Vector()) # no API for active vertex
        elif mode in {'EDIT_CURVE', 'EDIT_SURFACE'}:
            self.active_xyzt = (Vector((1,0,0)), Vector((0,1,0)), Vector((0,0,1)), Vector()) # no API for active vertex
    
    def coord_to_L(self, context, obj, coord, local_xyzt=None):
        obj_hash = (0 if obj is None else obj.as_pointer())
        if (self._last_obj_matrix is None) or (obj_hash != self._last_obj_hash):
            self._last_obj_hash = obj_hash
            self._last_obj_matrix = BlUtil.Object.matrix_world(obj)
        
        L_mode = self.L[0]
        if L_mode == 'BASIS':
            L = Vector(coord)
        elif L_mode == 'INDIVIDUAL':
            L = Vector()
        else:
            L_mode, R_mode, S_mode, to_m, persp = self.calc_matrix(context, obj, local_xyzt)
            L = matrix_inverted_safe(to_m) * (self._last_obj_matrix * Vector(coord))
            if L_mode in ('CAMERA', 'VIEW'):
                inv_z = ((1.0 / abs(L.z)) if L.z != 0.0 else 1.0)
                L = Vector((L.x * persp.x, L.y * persp.y, -L.z)).lerp(
                    Vector((L.x * inv_z * persp.x, L.y * inv_z * persp.y, -L.z)), persp.z)
        
        return L
    
    def coord_from_L(self, context, obj, L, local_xyzt=None):
        obj_hash = (0 if obj is None else obj.as_pointer())
        if (self._last_obj_matrix_inv is None) or (obj_hash != self._last_obj_hash):
            self._last_obj_hash = obj_hash
            self._last_obj_matrix_inv = matrix_inverted_safe(BlUtil.Object.matrix_world(obj))
        
        L = Vector(L)
        L_mode = self.L[0]
        if L_mode == 'BASIS':
            coord = L
        else:
            L_mode, R_mode, S_mode, to_m, persp = self.calc_matrix(context, obj, local_xyzt)
            if L_mode in ('CAMERA', 'VIEW'):
                L = Vector((L.x / persp.x, L.y / persp.y, -L.z)).lerp(
                    Vector((L.x * L.z / persp.x, L.y * L.z / persp.y, -L.z)), persp.z)
            coord = self._last_obj_matrix_inv * (to_m * L)
        
        return coord
    
    @classmethod
    def current(cls, context=None):
        if context is None: context = bpy.context
        manager = get_coordsystem_manager(context)
        return CoordSystemMatrix(manager.current, context=context)

@addon.PropertyGroup
class GridColorsPG:
    x = Color((1,0,0)) | prop("X")
    y = Color((0,1,0)) | prop("Y")
    z = Color((0,0,1)) | prop("Z")
    xy = Color((1,1,0)) | prop("XY")
    yz = Color((0,1,1)) | prop("YZ")
    xz = Color((1,0,1)) | prop("XZ")

@addon.IDBlock(name="Coordsys", icon='MANIPUL', show_empty=False)
class CoordSystemPG:
    items_LRS = [
        ('BASIS', "Basis", "Raw position/rotation/scale", 'BLENDER'),
        ('GLOBAL', "Global", "Global (world) coordinate system", 'WORLD'),
        ('PARENT', "Parent", "Parent's coordinate system (coincides with Global if there is no parent)", 'GROUP_BONE'),
        ('LOCAL', "Local", "Local coordinate system (coincides with Parent for non-edit modes)", 'EDITMODE_HLT'), # !!!!!
        ('INDIVIDUAL', "Individual", "Individual coordinate system", 'ROTATECOLLECTION'),
        ('ACTIVE', "Active", "Coordinate system of active object (coincides with Global if there is no active object)", 'ROTACTIVE'),
        ('OBJECT', "Object/bone", "Coordinate system of the specified object/bone", 'OBJECT_DATA'),
        ('CAMERA', "Camera", "Camera projection coordinate system", 'CAMERA_DATA'),
        ('VIEW', "View", "Viewport coordinate system", 'RESTRICT_VIEW_OFF'),
        ('WORKPLANE', "Workplane", "Workplane coordinate system", 'GRID'),
    ]
    items_L = items_LRS + [
        ('CURSOR', "Cursor", "3D cursor position", 'CURSOR'),
        ('MEAN', "Average", "Average of selected items' positions", 'ROTATECENTER'),
        ('CENTER', "Center", "Center of selected items' positions", 'ROTATE'),
        ('MIN', "Min", "Minimum of selected items' positions", 'FRAME_PREV'),
        ('MAX', "Max", "Maximum of selected items' positions", 'FRAME_NEXT'),
        ('PIVOT', "Pivot", "Position of the transform manipulator", 'MANIPUL'),
    ]
    items_R = items_LRS + [
        ('NORMAL', "Normal", "Orientation aligned to the average of elements' normals or bones' Y-axes", 'SNAP_NORMAL'),
        ('GIMBAL', "Gimbal", "Orientation aligned to the Euler rotation axes", 'NDOF_DOM'),
        ('ORIENTATION', "Orientation", "Specified orientation", 'MANIPUL'),
    ]
    items_S = items_LRS + [
        ('RANGE', "Range", "Use bounding box dimensions as the scale of each axis", 'BBOX'),
        ('STDDEV', "Deviation", "Use standard deviation as the scale of the system", 'STICKY_UVS_DISABLE'),
    ]
    
    icons_L = {item[0]:item[3] for item in items_L}
    icons_R = {item[0]:item[3] for item in items_R}
    icons_S = {item[0]:item[3] for item in items_S}
    
    icon_L = 'MAN_TRANS'
    icon_R = 'MAN_ROT'
    icon_S = 'MAN_SCALE'
    
    customizable_L = {'OBJECT', 'CAMERA', 'BOOKMARK'}
    customizable_R = {'OBJECT', 'CAMERA', 'ORIENTATION'}
    customizable_S = {'OBJECT', 'CAMERA'}
    
    def make_aspect(name, items):
        title = "{} type".format(name)
        @addon.PropertyGroup
        class CoordsystemAspect:
            mode = 'GLOBAL' | prop(title, title, items=items)
            obj_name = "" | prop() # object/orientation/bookmark name
            bone_name = "" | prop()
            def copy(self, template):
                self.mode = template.mode
                self.obj_name = template.obj_name
                self.bone_name = template.bone_name
        CoordsystemAspect.__name__ += name
        return CoordsystemAspect | prop()
    
    aspect_L = make_aspect("Origin", items_L)
    aspect_R = make_aspect("Orientation", items_R)
    aspect_S = make_aspect("Scale", items_S)
    
    del make_aspect
    
    used_modes = property(lambda self: {self.aspect_L.mode, self.aspect_R.mode, self.aspect_S.mode})
    
    _view_dependent_modes = {'VIEW', 'CURSOR', 'PIVOT', 'ORIENTATION'}
    @property
    def is_view_dependent(self):
        return any(aspect.mode in self._view_dependent_modes
            for aspect in (self.aspect_L, self.aspect_R, self.aspect_S))
    
    def unique_key(self, view_key):
        if not self.is_view_dependent: view_key = None
        return (self.name, view_key)
    
    extra_X = Vector((1, 0, 0)) | prop("X axis", "X axis")
    extra_Y = Vector((0, 1, 0)) | prop("Y axis", "Y axis")
    extra_Z = Vector((0, 0, 1)) | prop("Z axis", "Z axis")
    extra_T = Vector((0, 0, 0)) | prop("Translation", "Translation")
    
    def copy(self, template):
        self.aspect_L.copy(template.aspect_L)
        self.aspect_R.copy(template.aspect_R)
        self.aspect_S.copy(template.aspect_S)
        self.extra_X = Vector(template.extra_X)
        self.extra_Y = Vector(template.extra_Y)
        self.extra_Z = Vector(template.extra_Z)
        self.extra_T = Vector(template.extra_T)
    
    def bake(self, matrix, context=None):
        if not context: context = bpy.context
        csm = CoordSystemMatrix(self, context=context)
        m = csm.base_matrix(context)
        extra_m = matrix_inverted_safe(m) * matrix.to_4x4()
        self.extra_X, self.extra_Y, self.extra_Z, self.extra_T = matrix_decompose(extra_m)
    
    def base_matrix(self, context=None):
        if not context: context = bpy.context
        csm = CoordSystemMatrix(self, context=context)
        return csm.base_matrix(context)
    
    def final_matrix(self, context=None):
        if not context: context = bpy.context
        csm = CoordSystemMatrix(self, context=context)
        return csm.final_matrix(context)
    
    @property
    def extra_matrix(self):
        return matrix_compose(self.extra_X, self.extra_Y, self.extra_Z, self.extra_T)
    
    def make_reset(axis_id):
        def get_reset(self):
            return BlRna.is_default(getattr(self, "extra_"+axis_id), self, "extra_"+axis_id)
        
        def set_reset(self, value):
            context = bpy.context
            if UIMonitor.ctrl or UIMonitor.shift:
                # Get world coordinates of pivot
                csm = CoordSystemMatrix({"L":'PIVOT'}, context=context)
                m = csm.final_matrix(context)
                pos = m.translation
                
                # Transform to base matrix of this coordsystem
                csm = CoordSystemMatrix(self, context=context)
                m = csm.base_matrix(context)
                pos = matrix_inverted_safe(m) * pos
                if axis_id != "T":
                    pos = pos - csm.extra_matrix.translation
                elif UIMonitor.shift:
                    delta = pos - self.extra_T
                    self.extra_X -= delta
                    self.extra_Y -= delta
                    self.extra_Z -= delta
                
                setattr(self, "extra_"+axis_id, pos)
            elif value:
                setattr(self, "extra_"+axis_id, BlRna.get_default(self, "extra_"+axis_id))
        
        return False | prop("Click: reset {}, Ctrl+Click: set from pivot, Shift+Click: keep XYZ endpoints".format(axis_id), axis_id, get=get_reset, set=set_reset)
    
    reset_X = make_reset("X")
    reset_Y = make_reset("Y")
    reset_Z = make_reset("Z")
    reset_T = make_reset("T")
    
    def draw(self, layout):
        layout = NestedLayout(layout, addon.module_name+".coordsystem")
        
        with layout.column(True):
            self.draw_aspect(layout, "L")
            self.draw_aspect(layout, "R")
            self.draw_aspect(layout, "S")
        
        with layout.fold("Extra Matrix", folded=True): # folded by default
            with layout.column(True):
                self.draw_axis(layout, "X")
                self.draw_axis(layout, "Y")
                self.draw_axis(layout, "Z")
                self.draw_axis(layout, "T")
    
    def draw_axis(self, layout, axis_id):
        with layout.row(True):
            #with layout.row(True)(scale_x=0.1, enabled=(not getattr(self, "reset_"+axis_id))):
            with layout.row(True)(scale_x=0.1):
                layout.prop(self, "reset_"+axis_id, text=axis_id, toggle=True)
            layout.prop(self, "extra_"+axis_id, text="")
    
    def draw_aspect(self, layout, aspect_id):
        aspect = getattr(self, "aspect_"+aspect_id)
        aspect_icon = getattr(self, "icon_"+aspect_id)
        aspect_icons = getattr(self, "icons_"+aspect_id)
        customizable = getattr(self, "customizable_"+aspect_id)
        
        with layout.row(True):
            is_customizable = (aspect.mode in customizable)
            
            op = layout.operator("view3d.coordsystem_pick_aspect", text="", icon=aspect_icon)
            op.aspect_id = aspect_id
            
            with layout.row(True)(enabled=is_customizable):
                if aspect.mode == 'OBJECT':
                    obj = bpy.data.objects.get(aspect.obj_name)
                    with layout.row(True)(alert=bool(aspect.obj_name and not obj)):
                        layout.prop(aspect, "obj_name", text="")
                    
                    if obj and (obj.type == 'ARMATURE'):
                        bone = (obj.data.edit_bones if (obj.mode == 'EDIT') else obj.data.bones).get(aspect.bone_name)
                        with layout.row(True)(alert=bool(aspect.bone_name and not bone)):
                            layout.prop(aspect, "bone_name", text="")
                else:
                    layout.prop(aspect, "obj_name", text="")
            
            with layout.row(True)(scale_x=0.16):
                layout.prop(aspect, "mode", text="", icon=aspect_icons[aspect.mode])

@addon.Operator(idname="view3d.coordsystem_pick_aspect", options={'INTERNAL', 'REGISTER'}, description=
"Click: Pick this aspect from active object")
def Operator_Coordsystem_Pick_Aspect(self, context, event, aspect_id=""):
    manager = get_coordsystem_manager(context)
    coordsys = manager.current
    if not coordsys: return {'CANCELLED'}
    
    aspect = getattr(coordsys, "aspect_"+aspect_id)
    if aspect.mode != 'OBJECT': return {'CANCELLED'}
    
    obj = context.active_object
    if obj:
        aspect.obj_name = obj.name
        if obj.type == 'ARMATURE':
            bone = (obj.data.edit_bones if (obj.mode == 'EDIT') else obj.data.bones).active
            aspect.bone_name = (bone.name if bone else "")
        else:
            aspect.bone_name = ""
    else:
        aspect.obj_name = ""
        aspect.bone_name = ""
    
    return {'FINISHED'}

@addon.Operator(idname="view3d.coordsystem_new", options={'INTERNAL', 'REGISTER'}, description=
"Click: Copy current coordsystem, Ctrl+Click: bake current coordsystem, Shift+Click: bake manipulator, Alt+Click: bake workplane")
def Operator_Coordsystem_New(self, context, event):
    manager = get_coordsystem_manager(context)
    prev = manager.current
    if not prev:
        item = manager.coordsystems.new("Coordsys")
    else:
        if event.ctrl:
            item = manager.coordsystems.new(prev.name)
            item.bake(prev.final_matrix(context))
        elif event.shift:
            item = manager.coordsystems.new("Snapshot")
            csm = CoordSystemMatrix('MANIPULATOR', context=context)
            item.bake(csm.final_matrix(context))
        elif event.alt:
            item = manager.coordsystems.new("Snapshot")
            item.bake(CoordSystemMatrix.workplane_matrix(context, scaled=False))
        else:
            item = manager.coordsystems.new(prev.name)
            item.copy(prev)
    manager.coordsystem.selector = item.name
    return {'FINISHED'}

@addon.Operator(idname="view3d.coordsystem_delete", options={'INTERNAL', 'REGISTER'}, description="Delete coordsystem")
def Operator_Coordsystem_Delete(self, context, event):
    manager = get_coordsystem_manager(context)
    manager.coordsystems.discard(manager.coordsystem.selector)
    if manager.coordsystems:
        manager.coordsystem.selector = manager.coordsystems[len(manager.coordsystems)-1].name
    return {'FINISHED'}

@addon.PropertyGroup
class CoordSystemManagerPG:
    defaults_initialized = False | prop()
    coordsystems = [CoordSystemPG] | prop() # IDBlocks
    coordsystem = CoordSystemPG | prop() # IDBlock selector
    current = property(lambda self: self.coordsystems.get(self.coordsystem.selector))
    
    show_grid_xy = False | prop("Show grid XY plane", "Show grid XY")
    show_grid_yz = False | prop("Show grid YZ plane", "Show grid YZ")
    show_grid_xz = False | prop("Show grid XZ plane", "Show grid XZ")
    grid_size = 1.0 | prop("Grid size", "Grid size", min=0)
    grid_profile = 2 | prop("Grid profile", "Grid profile", min=-2, max=2)
    
    def draw(self, layout):
        with layout.row(True):
            layout.prop(self, "show_grid_xy", text="", icon='AXIS_TOP', toggle=True)
            layout.prop(self, "show_grid_xz", text="", icon='AXIS_FRONT', toggle=True)
            layout.prop(self, "show_grid_yz", text="", icon='AXIS_SIDE', toggle=True)
            layout.prop(self, "grid_profile", text="Grid")
            layout.prop(self, "grid_size", text="Size")
        
        self.coordsystem.draw(layout)
        coordsys = self.current
        if coordsys: coordsys.draw(layout)
    
    def init_default_coordystems(self):
        if self.defaults_initialized: return
        
        for item in CoordSystemPG.items_LRS:
            if item[0] == 'OBJECT': continue
            coordsys = self.coordsystems.new(item[1])
            coordsys.aspect_L.mode = item[0]
            coordsys.aspect_R.mode = item[0]
            coordsys.aspect_S.mode = item[0]
        
        coordsys = self.coordsystems.new("Normal")
        coordsys.aspect_L.mode = 'MEAN'
        coordsys.aspect_R.mode = 'NORMAL'
        coordsys.aspect_S.mode = 'GLOBAL'
        
        coordsys = self.coordsystems.new("Manipulator")
        coordsys.aspect_L.mode = 'PIVOT'
        coordsys.aspect_R.mode = 'ORIENTATION'
        coordsys.aspect_S.mode = 'GLOBAL'
        
        self.coordsystem.selector = "Global"
        
        self.defaults_initialized = True
    
    @addon.load_post
    def load_post(): # We can't do this in register() because of the restricted context
        manager = get_coordsystem_manager(bpy.context)
        if not manager.coordsystem.is_bound:
            manager.coordsystem.bind(manager.coordsystems, new="view3d.coordsystem_new", delete="view3d.coordsystem_delete", reselect=True)
        manager.init_default_coordystems() # assignment to selector must be done AFTER the binding
    del load_post
    
    @addon.after_register
    def after_register(): # We can't do this in register() because of the restricted context
        manager = get_coordsystem_manager(bpy.context)
        if not manager.coordsystem.is_bound:
            manager.coordsystem.bind(manager.coordsystems, new="view3d.coordsystem_new", delete="view3d.coordsystem_delete", reselect=True)
        manager.init_default_coordystems() # assignment to selector must be done AFTER the binding
    del after_register
    
    @addon.view3d_draw('POST_VIEW')
    def draw_view():
        context = bpy.context
        manager = get_coordsystem_manager(context)
        if not (manager.show_grid_xy or manager.show_grid_yz or manager.show_grid_xz): return
        
        csm = CoordSystemMatrix(manager.current, context=context)
        m = csm.final_matrix(context)
        
        prefs = addon.preferences
        def get_color(color_name):
            c = getattr(prefs.gridcolors, color_name)
            return [c[0], c[1], c[2], 1.0]
        color_x = get_color("x")
        color_y = get_color("y")
        color_z = get_color("z")
        color_xy = get_color("xy")
        color_yz = get_color("yz")
        color_xz = get_color("xz")
        
        pw = manager.grid_profile
        sz = manager.grid_size
        steps = prefs.gridstep_small
        steps_big = steps * prefs.gridstep_big
        isz = int(sz*steps)
        
        show_grid_x = manager.show_grid_xy or manager.show_grid_xz
        show_grid_y = manager.show_grid_xy or manager.show_grid_yz
        show_grid_z = manager.show_grid_xz or manager.show_grid_yz
        
        def calc_q(q):
            if pw >= 1:
                q = lerp(math.sqrt(1.0 - q*q), 1.0, pw-1.0)
            elif pw >= 0:
                q = lerp(1.0 - q, math.sqrt(1.0 - q*q), pw)
            elif pw >= -1:
                q = 1.0 - q
                q = lerp(q, 1.0 - math.sqrt(1.0 - q*q), -pw)
            else:
                q = 1.0 - q
                q = lerp(1.0 - math.sqrt(1.0 - q*q), 0.0, -pw-1.0)
            return q
        
        def drawline(batch, p0, p1):
            batch.vertex(*(m * Vector(p0)))
            batch.vertex(*(m * Vector(p1)))
        
        def drawgrid(batch, xi, yi, color):
            if pw <= -2: return
            p0 = [0,0,0]
            p1 = [0,0,0]
            
            for i in range(-isz, isz+1):
                if i == 0: continue
                w = i/steps
                
                q = abs(w/sz)
                q = calc_q(q)
                q = sz*q
                
                color[-1] = (0.5 if i % steps_big == 0 else 0.125)
                cgl.Color = color
                
                p0[xi] = -q; p0[yi] = w
                p1[xi] = q; p1[yi] = w
                drawline(batch, p0, p1)
                
                p0[yi] = -q; p0[xi] = w
                p1[yi] = q; p1[xi] = w
                drawline(batch, p0, p1)
        
        with cgl(LineWidth=1, DepthMask=False, DEPTH_TEST=False, BLEND=True, LINE_STIPPLE=True):
            with cgl.batch('LINES') as batch:
                if show_grid_x:
                    cgl.Color = color_x
                    drawline(batch, (-sz,0,0), (0,0,0))
                
                if show_grid_y:
                    cgl.Color = color_y
                    drawline(batch, (0,-sz,0), (0,0,0))
                
                if show_grid_z:
                    cgl.Color = color_z
                    drawline(batch, (0,0,-sz), (0,0,0))
        
        with cgl(LineWidth=1, DepthMask=False, DEPTH_TEST=False, BLEND=True, LINE_STIPPLE=False):
            with cgl.batch('LINES') as batch:
                if show_grid_x:
                    cgl.Color = color_x
                    #drawline(batch, (-sz,0,0), (sz,0,0))
                    drawline(batch, (0,0,0), (sz,0,0))
                
                if show_grid_y:
                    cgl.Color = color_y
                    #drawline(batch, (0,-sz,0), (0,sz,0))
                    drawline(batch, (0,0,0), (0,sz,0))
                
                if show_grid_z:
                    cgl.Color = color_z
                    #drawline(batch, (0,0,-sz), (0,0,sz))
                    drawline(batch, (0,0,0), (0,0,sz))
                
                if manager.show_grid_xy: drawgrid(batch, 0, 1, color_xy)
                if manager.show_grid_yz: drawgrid(batch, 1, 2, color_yz)
                if manager.show_grid_xz: drawgrid(batch, 0, 2, color_xz)
    del draw_view
    
    #@addon.view3d_draw('POST_PIXEL')
    #def draw_px():
    #    manager = get_coordsystem_manager(bpy.context)
    #del draw_px

def get_coordsystem_manager(context=None):
    if context is None: context = bpy.context
    #return context.screen.coordsystem_manager
    return addon.internal.coordsystem_manager

# We need to store all coordsystems in one place, so each screen can't have an independent list of coordinate systems
#addon.type_extend("Screen", "coordsystem_manager", (CoordSystemManagerPG | prop()))
addon.Internal.coordsystem_manager = CoordSystemManagerPG | prop()

@LeftRightPanel(idname="VIEW3D_PT_coordsystem", space_type='VIEW_3D', category="Transform", label="Coordinate System")
class Panel_Coordsystem:
    def draw(self, context):
        layout = NestedLayout(self.layout)
        get_coordsystem_manager(context).draw(layout)
