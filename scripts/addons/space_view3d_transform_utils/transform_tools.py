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
import itertools

import mathutils.geometry
from mathutils import Color, Vector, Euler, Quaternion, Matrix

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_math import lerp, matrix_LRS, matrix_compose, matrix_decompose, matrix_inverted_safe, orthogonal_XYZ, orthogonal, matrix_flatten, matrix_unflatten
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
#from . import batch_transform

from .coordsystems import *
#from .batch_transform import *

addon = AddonManager()

#============================================================================#

def workplane_matrix(context, scaled):
    tfm_tools = get_transform_tools(context)
    workplane = tfm_tools.workplane
    return (workplane.matrix_scaled if scaled else workplane.matrix)
CoordSystemMatrix.workplane_matrix = staticmethod(workplane_matrix)
del workplane_matrix

"""
TODO:
    * generic transform operator (in particular, for cursor, workplane, refpoints)
        * implement snap_cast (combine select, raycast and depthcast)
        * switch absolute/relative coords (mostly useful for snapping to grid/increments, as it defines the grid origin)
        * switch coordinate systems
        * switch move/rotate/scale modes
        * axis locks
        * header display of modes/coordinates
            * customizable precision
        * snap to bbox/faces/edges/vertices/grid
        * snap to raw/preview/render mesh
        * flat or interpolated normal
        * option to snap only to solid?
        * snap cursor to workplane's plane (if it's visible)
        * option to adjust cursor and view when picking workplane? (also: adjust workplane and view when picking cursor position)
        * options to draw guides and snap elements (?)
        * moth3r asks for an operator to "pick an edge" (so that workplane's main axis will be rotated parallel to the picked edge)
        * SketchUp's 3-click workplane/coordsystem setup? see https://www.youtube.com/watch?v=Hp_iTKs7Xcc
    
    * [DONE] cursor/workplane/refpoint attachment
        * [DONE] option to display coordinates in attachment space or in current coordsystem
    
    * snap/align/match commands and spatial queries
    
    * cursor history (not so useful for workplane/refpoints, since they can be stored in scene and reverted with undo/redo)
    
    * make all 3d-render callbacks priority-sorted; make cursor hiding a "high-priority" view3d callback
    
    * CAD-like guides?
    
    * copy/paste to workplane? (moth3r's idea, not really sure what he meant)

WARNING: in current implementation, 3D-cursor-related functions work only for the main (scene) cursor. They ignore the local-view cursor.

Auto initialization (binding) of IDBlock selectors by property path? Generic new/delete operators?


* [DONE] allow to switch to ortho mode when not aligned to workplane (at least until view is rotated)
* [DONE] implement workplane position in current coordsystem (not rotation, because of the euler wrapping)


make an option to navigate around workplane even if it's not visible
(i.e. make workplane visibility and navigation around workplane separate options)
(also, make preference to synchronize it with workplane visibility)
moth3r suggests to use 'PINNED' icon? or maybe put it in a menu, as it's probably a rarely-used feature

low priority: remember what was the last mode before view was snapped to top/side view
    make an option to always override blender's defaults, not just when workplane is visible
    write it in documentation

make options to turn off panels completely (for batch operations and transform tools)




Ideas from http://blenderartists.org/forum/showthread.php?236764-Blender-as-a-CAD-Arch-viz-tool-8-)&highlight=
1. Unit&precision control
2. While-in-command Osnap modes (midpoint, endpoint, center, intersection, tangent, parallel, perpendicular, etc etc) w/magnet !
4. While-in-command zoom/pan (w/mouse)
3. User Coordinate System easy to manipulate
5. Basic easy operations: offset, mirror, array (X,Y,Z), rotate, scale
6. Above to be accessible also w/ reference points (see Autocad)
7. A basic set of geometric primitives: line, poly, point
That could be also clearly visible in eg. Sketchup.

see also:
http://blenderartists.org/forum/showthread.php?365078-User-Coordinate-Space-request-for-feedback
http://blenderartists.org/forum/showthread.php?255662-GSOC-2012-Precision-Modelling-Tools
http://blenderartists.org/forum/showthread.php?256295-Script-to-align-objects-to-a-face-and-line-on-that-face
http://blenderartists.org/forum/showthread.php?326991-Transform-Orientations-typical-interaction-use-case-%28workflow-UI%29
http://www.cad4arch.com/cadtools/




\\ Other quick actions for refpoints: Modifier+Click on refpoint -> show/hide? raycast?
# AB - line from A to B; -AB - line from B to A; A1 - line from A to A1; -A1 - line from A1 to A; A1B - line from A1 to B; A1B1 - line from A1 to B1
# three points define a plane or a normal to plane
# move A B - moves from A to B
# move A B 0.5 - moves from A to ensude distance 0.5 to B
# move[object: :O, geometry: :G] [individual: *]FROM TO [distance: a number] [use grid/increment: #] [lock axes: lowercase xyz] // increment/lock coordsystem is specified outside of the command line (or: simply use current coordsystem?)
#   some special cases: (closest | origin | mean | center | min | max) * (objects' origins | geometry); world, cursor, workplane, pivot, active ?

selection (aliases: sel, s) - objects are transformed along with their geometry
objects (aliases: obj, o) - geometry remains in place
geometry (aliases: geo, gmt, gry, g) - objects' matrices remain the same
cursor (aliases: cur, c)
workplane (aliases: plane, pln, wrk, p)
coordsystem? (aliases: system, sys, t)

world (aliases: wrl, wrd, w)
active (aliases: act, a)
view (aliases: v)
normal (aliases: nor, n)
mean (aliases: avg)
center (aliases: cnt, ctr, cen)
min
max
manipulator? (aliases: man, m) (used for pivot / current orientation)

capital letters - refpoints

* - individual mode
& - closest/nearest mode
# - grid/increment

+/- x/y/z axes? arbitrary offsets?

> snap/move
: align/rotate
/ match/scale


examples:
* align objects to workplane (individually, use nearest axes): s*&:p
* snap objects to workplane: (individually, projecting on workplane's XY plane): s*>p.z
* align workplane to world's -XZ: p:w.-xz

Syntax: WHAT [FROM] OPERATION TO
if FROM is not specified, it is considered the same as WHAT


queries:
& - and
| - or
! - not
( ) - parentheses
mag(a - b) - euclidean distance between a and b ((x^2+y^2+z^2)^0.5)
man(a - b) - manhattan distance between a and b (|x|+|y|+|z|)
max(a - b) - max axis (max(|x|, |y|, |z|))
mag(a - b.xy) - distance from a's position to b's XY plane
dist(a, b) - distance to b's geometry ?
angle(a.z, b.z) - angle between vectors
angle(obj - cam, cam.-z) - angle to object from camera's forward direction
ray(a, b) - raycast from a to b ?

What: Selection, Cursor, Workplane
Snap location, Snap geometry origin, Look at:
    From: Individual, Cursor, Pivot, World origin, Active, Coordsystem origin, Workplane, (Mean, Center, Min, Max)*(origins, geometry), Closest, Refpoints
    To: Grid, Cursor, Pivot, World origin, Active, Coordsystem origin, Workplane, (Mean, Center, Min, Max)*(origins, geometry), Refpoints
Align (parallel to, orthogonal to, arbitrary angle to?):
    From: Individual X/Y/Z, World X/Y/Z, Active X/Y/Z, Camera X/Y/Z, View X/Y/Z, Workplane X/Y/Z, Normal X/Y/Z, Orientation X/Y/Z, Refpoints
    To: World X/Y/Z, Active X/Y/Z, Camera X/Y/Z, View X/Y/Z, Workplane X/Y/Z, Normal X/Y/Z, Orientation X/Y/Z, Refpoints
Options:
    objects or geometry origin or geometry (Mean, Center, Min, Max)
        transform object and geometry along with it
        transform object, keep geometry in place
        transform geometry, keep object in place
    individual or as a whole (rigid system)
    all axes or only some axes ("projection")

For snapping, 2 points must be specified
For aligning, 4 points must be specified
    
* option: snap/align selection as a whole or each element individually
* ability to align workplane to object / polygon / plane
* "axis-matching rotation" operator (rotate selection to make one vector parallel to another)
* add operation to align object to workplane via its face
    think of an operation to "unrotate" an object which has rotated data
    \\ as an example (though probably not optimal):
    http://blenderartists.org/forum/showthread.php?256295-Script-to-align-objects-to-a-face-and-line-on-that-face

* Workplane from world/view/object/orientation/coordsystem XY/YZ/XZ
* Workplane from selection (orthogonal to normal)
* Workplane from 3D-view-picked normal
* Workplane from 3 selected objects/elements (will lie in the plane)
* Workplane from 2 selected objects/elements (will be orthogonal to line)

@addon.PropertyGroup
class SnapPointPG:
    coordsystem = "" | prop()
    use_geometry = False | prop()
    mode = '' | prop(items=[('ZERO', "Zero"), ('ACTIVE', "Active"), ('WORKPLANE', "Workplane"), ('CURSOR', "Cursor"), ('PIVOT', "Pivot"), ('ORIGIN', "Origin"), ('MEAN', "Mean"), ('CENTER', "Center"), ('MIN', "Min"), ('MAX', "Max")])
    offset = Vector() | prop()

@addon.PropertyGroup
class SnapAlignOperationPG: # maybe a better-fitting name is Match?
    move = False | prop()
    rotate = False | prop()
    scale = False | prop()
    transform_object = True | prop()
    transform_geometry = True | prop()
    src0 = SnapPointPG | prop()
    src1 = SnapPointPG | prop()
    dst0 = SnapPointPG | prop()
    dst1 = SnapPointPG | prop()
    individual = False | prop()
    increment = False | prop()
    closest = False | prop()
    distance = 0.0 | prop()
    angle = 0.0 | prop()
    factor = 1.0 | prop()
    lock_coordsystem = "" | prop()
    lock_axes = {} | prop(items=['X', 'Y', 'Z'])

@addon.Menu(idname="VIEW3D_MT_transform_tools_spatial_queries", label="Spatial queries", description="Spatial queries")
def Menu_Spatial_Queries(self, context):
    layout = NestedLayout(self.layout)
    layout.label("Distance to point/curve/surface/volume") # special cases: planes
    layout.label("Intersection with point/curve/surface/volume") # special cases: half-spaces
    layout.label("Angle to point/vector")
    layout.label("Raycast from point/vector")
"""

# =========================================================================== #
#                            < TRANSFORM TOOLS >                              #
# =========================================================================== #

def make_attach_info(entity_name, options_keys, on_update=None, on_set=None):
    options_items = []
    use_cs_attach = False
    for key in options_keys:
        if key == 'CS_DISPLAY':
            options_items.append(('CS_DISPLAY', "Display in current CS", "Display coordinates in current coordsystem"))
        elif key == 'CS_ATTACH':
            use_cs_attach = True
            options_items.append(('CS_ATTACH', "Attach to coordsystem", "Attach to coordsystem (instead of object)"))
        elif key == 'INHERIT':
            options_items.append(('INHERIT', "Inherit", "Inherit attachment options"))
    
    @addon.PropertyGroup
    class AttachInfoPG:
        def check_workplane(self):
            if not self.obj_name: return False
            if use_cs_attach: return False
            
            is_work_name = (self.obj_name in WorkplanePG.workobj_names)
            if not is_work_name:
                obj = bpy.data.objects.get(self.obj_name)
                is_work_name = any(obj.name in WorkplanePG.workobj_names for obj in BlUtil.Object.parents(obj, True))
            
            if is_work_name:
                self.obj_name = ""
                messagebox("Attaching {} to Workplane is forbidden".format(entity_name), icon='ERROR')
            
            return is_work_name
        
        def options_update(self, context):
            if on_update: on_update(BlRna.parent(self), context)
        options_base = {} | prop("Options", "Options", items=options_items, update=options_update)
        
        def coordsys_name_update(self, context):
            if on_update: on_update(BlRna.parent(self), context)
        coordsys_name_base = "" | prop("Coordinate system", update=coordsys_name_update) # TODO: use actual IDBlock selector?
        
        def obj_name_update(self, context):
            if self.check_workplane(): return
            if on_update: on_update(BlRna.parent(self), context)
        obj_name_base = "" | prop("Object", update=obj_name_update)
        
        def bone_name_update(self, context):
            if on_update: on_update(BlRna.parent(self), context)
        bone_name_base = "" | prop("Bone", update=bone_name_update)
        
        def _get(self):
            return BlRna.enum_to_int(self, "options_base")
        def _set(self, value):
            if on_set: on_set(BlRna.parent(self))
            self.options_base = BlRna.enum_from_int(self, "options_base", value)
        options = {} | prop("Options", "Options", items=options_items, get=_get, set=_set)
        
        def _get(self):
            return self.coordsys_name_base
        def _set(self, value):
            if on_set: on_set(BlRna.parent(self))
            self.coordsys_name_base = value
        coordsys_name = "" | prop("Coordinate system", get=_get, set=_set)
        
        def _get(self):
            return self.obj_name_base
        def _set(self, value):
            if on_set: on_set(BlRna.parent(self))
            self.obj_name_base = value
        obj_name = "" | prop("Object", get=_get, set=_set)
        
        def _get(self):
            return self.bone_name_base
        def _set(self, value):
            if on_set: on_set(BlRna.parent(self))
            self.bone_name_base = value
        bone_name = "" | prop("Bone", get=_get, set=_set)
        
        matrix_array = Matrix() | prop()
        def _get(self):
            return self.matrix_array # returns Matrix
        def _set(self, value):
            self.matrix_array = matrix_flatten(value) # requires linear array
        matrix = property(_get, _set)
        matrix_exists = False | prop()
        
        def copy(self, template):
            self.options = template.options
            self.coordsys_name = template.coordsys_name
            self.obj_name = template.obj_name
            self.bone_name = template.bone_name
        
        def calc_matrix(self, context=None):
            if context is None: context = bpy.context
            if 'CS_ATTACH' in self.options:
                manager = get_coordsystem_manager(context)
                coordsys = manager.coordsystems.get(self.coordsys_name)
                return (bool(coordsys), CoordSystemMatrix(coordsys, context=context).final_matrix())
            else:
                obj = bpy.data.objects.get(self.obj_name)
                return (bool(obj), BlUtil.Object.matrix_world(obj, self.bone_name))
        
        def draw(self, layout, inherit=False, parent=None):
            if inherit and parent:
                attach_info = parent
            else:
                attach_info = self
            
            with layout.row(True)(active=not inherit):
                cs_attach = ('CS_ATTACH' in attach_info.options)
                cs_display = ('CS_DISPLAY' in attach_info.options)
                
                if cs_attach:
                    icon = ('OUTLINER_DATA_EMPTY' if cs_display else 'MANIPUL') # or 'OUTLINER_OB_EMPTY'
                else:
                    icon = ('MESH_CUBE' if cs_display else 'OBJECT_DATA')
                layout.prop_menu_enum(self, "options", text="", icon=icon) # this is always the self
                
                with layout.row(True)(enabled=not inherit):
                    if cs_attach:
                        layout.prop(attach_info, "coordsys_name", text="")
                    else:
                        obj = bpy.data.objects.get(attach_info.obj_name)
                        with layout.row(True)(alert=bool(attach_info.obj_name and not obj)):
                            layout.prop(attach_info, "obj_name", text="")
                        
                        if obj and (obj.type == 'ARMATURE'):
                            bone = (obj.data.edit_bones if (obj.mode == 'EDIT') else obj.data.bones).get(self.bone_name)
                            with layout.row(True)(alert=bool(attach_info.bone_name and not bone)):
                                layout.prop(attach_info, "bone_name", text="")
    
    return AttachInfoPG | prop()

@addon.PropertyGroup
class WorkplanePG:
    worksurf_name = "[Worksurface]"
    workpolar_name = "[Workpolar]"
    workgrid_name = "[Workgrid]"
    workplane_name = "[Workplane]"
    workobj_names = {worksurf_name, workpolar_name, workgrid_name, workplane_name}
    
    def work_obj_get(self, name, scene=None, create=False, parent=None):
        work_obj = bpy.data.objects.get(name)
        if work_obj and (work_obj.type != 'MESH'): work_obj = None
        
        if create and (not work_obj):
            mesh = bpy.data.meshes.get(name)
            if not mesh: mesh = bpy.data.meshes.new(name)
            work_obj = bpy.data.objects.new(name, mesh)
            work_obj.name = name # in case of same-named objects
            self.work_obj_update_settings(work_obj, True)
            self.work_obj_update_mesh(work_obj)
            work_obj.parent = parent
            self.matrices_initialized = False
        
        if work_obj and scene and (name not in scene.objects):
            scene.objects.link(work_obj)
            scene.update()
        
        return work_obj
    
    def work_obj_update_settings(self, work_obj, all_settings=False):
        if not work_obj: return
        
        scene = bpy.context.scene
        
        if work_obj.name == self.worksurf_name:
            hide = not self.snap_any
        elif work_obj.name == self.workpolar_name:
            hide = not self.snap_to_polar
        elif work_obj.name == self.workgrid_name:
            hide = not self.snap_to_cartesian
        else: # workplane_name
            hide = True
        
        hide |= (not self.matrices_initialized)
        
        if work_obj.hide != hide: work_obj.hide = hide
        if work_obj.hide_render != True: work_obj.hide_render = True
        if work_obj.hide_select != True: work_obj.hide_select = True
        if work_obj.select != False: work_obj.select = False
        if scene.objects.active == work_obj: scene.objects.active = None
        
        if not all_settings: return
        
        for i in range(len(work_obj.layers)):
            work_obj.layers[i] = True
        work_obj.show_name = False
        work_obj.show_axis = False
        work_obj.show_wire = False
        work_obj.show_all_edges = False
        work_obj.show_bounds = False
        work_obj.show_texture_space = False
        work_obj.show_x_ray = False
        work_obj.show_transparent = False
        work_obj.draw_bounds_type = 'BOX'
        work_obj.draw_type = 'BOUNDS'
    
    def work_obj_update_mesh(self, work_obj):
        if not work_obj: return
        if work_obj.name == self.workplane_name: return
        
        mesh = work_obj.data
        bm = bmesh.new()
        
        if work_obj.name == self.worksurf_name:
            if self.limit == 0:
                bmesh.ops.create_circle(bm, cap_ends=True, cap_tris=False, segments=8, diameter=2.0) # actually, radius?
            else:
                bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0) # actually, halfsize?
        elif work_obj.name == self.workpolar_name:
            if self.limit == 0:
                v0 = bm.verts.new(Vector())
                n = self.polar_subdivs
                for i in range(n):
                    w = (i/n) * math.pi * 2
                    v1 = bm.verts.new(Vector((math.sin(w), math.cos(w), 0.0)))
                    bm.edges.new((v0, v1))
            else:
                # make sure bounds are (-1,1) square
                bm.verts.new(Vector((-1, -1, 0)))
                bm.verts.new(Vector((1, 1, 0)))
                v0 = bm.verts.new(Vector())
                n = self.polar_subdivs
                for i in range(n):
                    w = (i/n) * math.pi * 2
                    p = Vector((math.sin(w), math.cos(w), 0.0))
                    p *= (1.0 / max(abs(p.x), abs(p.y)))
                    v1 = bm.verts.new(p)
                    bm.edges.new((v0, v1))
        elif work_obj.name == self.workgrid_name:
            if self.limit == 0:
                # make sure bounds are out of visibility range
                far_enough = 1e5
                bm.verts.new(Vector((-far_enough, -far_enough, 0)))
                bm.verts.new(Vector((far_enough, far_enough, 0)))
                n = (self.max_grid_ivdist // 2) + 1
            else:
                bm.verts.new(Vector((-self.limit, -self.limit, 0)) * self.scale)
                bm.verts.new(Vector((self.limit, self.limit, 0)) * self.scale)
                n = self.limit
            
            x0, x1, y0, y1 = [], [], [], []
            for iy in range(-n, n+1):
                for ix in range(-n, n+1):
                    v = bm.verts.new(Vector((ix, iy, 0.0)) * self.scale)
                    if (ix == -n): x0.append(v)
                    elif (ix == n): x1.append(v)
                    if (iy == -n): y0.append(v)
                    elif (iy == n): y1.append(v)
            for v0, v1 in zip(x0, x1):
                bm.edges.new((v0, v1))
            for v0, v1 in zip(y0, y1):
                bm.edges.new((v0, v1))
        
        bm.to_mesh(mesh)
    
    def work_obj_delete(self, work_obj):
        if not work_obj: return
        mesh = work_obj.data
        for scene in bpy.data.scenes:
            if work_obj.name in scene.objects: scene.objects.unlink(work_obj)
        if work_obj.users == 0: bpy.data.objects.remove(work_obj)
        if mesh and (mesh.users == 0): bpy.data.meshes.remove(mesh)
    
    def get_workplane_objs(self):
        worksurf_obj = self.work_obj_get(self.worksurf_name)
        workpolar_obj = self.work_obj_get(self.workpolar_name)
        workgrid_obj = self.work_obj_get(self.workgrid_name)
        workplane_obj = self.work_obj_get(self.workplane_name)
        return workplane_obj, worksurf_obj, workpolar_obj, workgrid_obj
    
    def ensure_workplane_objs(self, update_settings=False):
        scene = bpy.context.scene
        workplane_obj = self.work_obj_get(self.workplane_name, scene, True)
        worksurf_obj = self.work_obj_get(self.worksurf_name, scene, True, workplane_obj)
        workpolar_obj = self.work_obj_get(self.workpolar_name, scene, True, worksurf_obj)
        # not a child of workplane_obj to avoid relationship line visualization
        workgrid_obj = self.work_obj_get(self.workgrid_name, scene, True)
        
        if update_settings:
            self.work_obj_update_settings(worksurf_obj)
            self.work_obj_update_settings(workpolar_obj)
            self.work_obj_update_settings(workgrid_obj)
            self.work_obj_update_settings(workplane_obj)
    
    def update_workplane_objs(self):
        worksurf_obj = self.work_obj_get(self.worksurf_name)
        workpolar_obj = self.work_obj_get(self.workpolar_name)
        workgrid_obj = self.work_obj_get(self.workgrid_name)
        workplane_obj = self.work_obj_get(self.workplane_name)
        
        self.work_obj_update_settings(worksurf_obj)
        self.work_obj_update_settings(workpolar_obj)
        self.work_obj_update_settings(workgrid_obj)
        self.work_obj_update_settings(workplane_obj)
        
        self.work_obj_update_mesh(worksurf_obj)
        self.work_obj_update_mesh(workpolar_obj)
        self.work_obj_update_mesh(workgrid_obj)
        self.work_obj_update_mesh(workplane_obj)
    
    def delete_workplane_objs(self):
        self.work_obj_delete(self.work_obj_get(self.workgrid_name))
        self.work_obj_delete(self.work_obj_get(self.workpolar_name))
        self.work_obj_delete(self.work_obj_get(self.worksurf_name))
        self.work_obj_delete(self.work_obj_get(self.workplane_name))
    
    # ==================================================================== #
    
    def on_attach_update(self, context):
        old_exists, old_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        new_exists, new_matrix = self.attach_info.calc_matrix()
        if (new_matrix == old_matrix): return
        xyzt = self.plane_xyzt
        self.attach_info.matrix = new_matrix
        self.attach_info.matrix_exists = new_exists
        self.plane_xyzt = xyzt
    attach_info = make_attach_info("Workplane", ['CS_DISPLAY'], on_attach_update)
    
    def _get(self):
        userprefs = bpy.context.user_preferences
        return (userprefs.edit.object_align == 'WORLD')
    def _set(self, value):
        userprefs = bpy.context.user_preferences
        userprefs.edit.object_align = ('WORLD' if value else 'VIEW')
    use_world = True | prop("Align new objects to world or to view", get=_get, set=_set)
    
    forced_view_alignment = False
    prev_region = None
    prev_region_rot = None
    
    def _update_snap(self, context):
        if self.snap_any:
            self.ensure_workplane_objs()
            self.block_navigation_operators(True)
        else:
            self.delete_workplane_objs()
            self.block_navigation_operators(False)
    snap_to_plane = False | prop("Enable workplane", update=_update_snap)
    snap_to_cartesian = False | prop("Enable snapping grid", update=_update_snap)
    snap_to_polar = False | prop("Enable snapping angles", update=_update_snap)
    snap_any = property(lambda self: self.snap_to_plane or self.snap_to_cartesian or self.snap_to_polar)
    
    swap_axes = False | prop("Adjust workplane to viewing direction")
    
    def _update_params(self, context):
        self.update_workplane_objs()
        self.align_to_view(True)
    scale = 1.0 | prop("Grid scale", subtype='DISTANCE', unit='LENGTH', min=0.01, max=100, update=_update_params)
    polar_subdivs = 8 | prop("Number of snapping angles", min=3, max=500, update=_update_params)
    limit = 0 | prop("Size limit", min=0, max=100, update=_update_params)
    
    # ===== plane_xyzt ===== #
    plane_x = Vector((1,0,0)) | prop()
    plane_y = Vector((0,1,0)) | prop()
    plane_z = Vector((0,0,1)) | prop()
    plane_t = Vector((0,0,0)) | prop()
    
    @staticmethod
    def transform_plane(m, x, y, z, t):
        p0 = Vector(t)
        px = p0 + Vector(x)
        py = p0 + Vector(y)
        pz = p0 + Vector(z)
        
        p0 = m * p0
        px = m * px
        py = m * py
        pz = m * pz
        
        t = p0
        y = (py - p0).normalized()
        z = (px - p0).cross(y).normalized()
        x = y.cross(z)
        
        return (x, y, z, t)
    
    def _get(self):
        m = self.attach_info.matrix
        return self.transform_plane(m, self.plane_x, self.plane_y, self.plane_z, self.plane_t)
    def _set(self, xyzt):
        m = matrix_inverted_safe(self.attach_info.matrix)
        self.plane_x, self.plane_y, self.plane_z, self.plane_t = self.transform_plane(m, *xyzt)
        self.plane_rot_cache_from_xyz()
        self.align_to_view(True)
    plane_xyzt = property(_get, _set) # global
    
    def _get(self):
        return matrix_compose(*self.plane_xyzt)
    def _set(self, value):
        self.plane_xyzt = matrix_decompose(value)
    matrix = property(_get, _set) # global
    
    def _get(self):
        m = self.matrix
        m.col[0] *= self.scale
        m.col[1] *= self.scale
        m.col[2] *= self.scale
        return m
    matrix_scaled = property(_get) # global
    
    _csm_matrix = None
    def _get(self):
        if ('CS_DISPLAY' in self.attach_info.options):
            m = CoordSystemMatrix.current().final_matrix()
            world_t = self.attach_info.matrix * self.plane_t
            return matrix_inverted_safe(m) * world_t
        else:
            return self.plane_t
    def _set(self, value):
        if ('CS_DISPLAY' in self.attach_info.options):
            cls = self.__class__
            if not UIMonitor.user_interaction:
                UIMonitor.user_interaction = True
                m = CoordSystemMatrix.current().final_matrix()
                cls._csm_matrix = m
            else:
                m = cls._csm_matrix or Matrix()
            world_t = m * Vector(value)
            self.plane_t = matrix_inverted_safe(self.attach_info.matrix) * world_t
        else:
            self.plane_t = Vector(value)
        self.align_to_view(True)
    plane_pos = Vector() | prop(get=_get, set=_set, subtype='TRANSLATION', unit='LENGTH') # local/display
    
    def plane_rot_cache_from_xyz(self):
        m = matrix_compose(self.plane_x, -self.plane_z, self.plane_y)
        value = m.to_euler('YXZ')
        value = Euler((value[0]+math.radians(90), value[2], value[1]))
        self.plane_rot_cache = Vector(value)
    def plane_rot_cache_to_xyz(self):
        value = self.plane_rot_cache
        value = Euler((value[0]-math.radians(90), value[2], value[1]), 'YXZ')
        m = value.to_matrix()
        self.plane_x, self.plane_y, self.plane_z = m.col[0], m.col[2], -m.col[1]
        self.align_to_view(True)
    plane_rot_cache = Vector() | prop() # local/display ?
    
    def _get(self):
        return Euler(self.plane_rot_cache)
    def _set(self, value):
        self.plane_rot_cache = Vector(value)
        self.plane_rot_cache_to_xyz()
    plane_rot = Euler() | prop(get=_get, set=_set) # local/display ?
    # ====================== #
    
    matrices_initialized = False | prop()
    last_axis_choice = 0 | prop()
    max_dist = 1000.0 | prop()
    view_pos = Vector() | prop()
    view_proj = Vector() | prop()
    view_dist = 0.0 | prop()
    view_range = 1000.0 | prop()
    view_xy = Vector((0,0)) | prop()
    view_ixy = (0,0) | prop()
    max_idist = 0 | prop()
    max_grid_ivdist = 100
    
    def block_navigation_operators(self, block):
        if block:
            # view3d.view_all is blocked because it takes into account the (huge) workplane
            UIMonitor.block_operator("view3d.view_all", self.blocked_navigation_callback)
            UIMonitor.block_operator("view3d.viewnumpad", self.blocked_navigation_callback)
            UIMonitor.block_operator("view3d.view_orbit", self.blocked_navigation_callback)
        else:
            UIMonitor.unblock_operator("view3d.view_all")
            UIMonitor.unblock_operator("view3d.viewnumpad")
            UIMonitor.unblock_operator("view3d.view_orbit")
    
    @staticmethod
    def blocked_navigation_callback(op_info, context, event):
        op_idname, op_props = op_info
        if op_idname == "view3d.view_all":
            bpy.ops.view3d.view_all_workplane('INVOKE_DEFAULT', use_all_regions=op_props["use_all_regions"], center=op_props["center"])
        elif op_idname == "view3d.viewnumpad":
            if (op_props["type"] == 'CAMERA') or op_props["align_active"]: return True
            bpy.ops.view3d.align_view_to_workplane('INVOKE_DEFAULT', mode=op_props["type"])
        elif op_idname == "view3d.view_orbit":
            bpy.ops.view3d.orbit_around_workplane('INVOKE_DEFAULT', mode=op_props["type"])
    
    def draw(self, layout):
        title = "Workplane"
        with layout.row(True):
            with layout.fold("", ("row", True), False, key=title):
                is_folded = layout.folded
            with layout.row(True)(alignment='LEFT'):
                layout.label(title)
            with layout.row(True)(alignment='RIGHT'):
                layout.prop(self, "swap_axes", text="", icon='MANIPUL')
                layout.operator("view3d.align_view_to_workplane", text="", icon='LAMP_AREA')
        
        # layout.operator("view3d.snap_cursor_workplane", text="", icon='CURSOR')
        # layout.operator("view3d.align_objects_to_workplane", text="", icon='OBJECT_DATA')
        
        if not is_folded:
            with layout.column(True):
                with layout.row(True):
                    self.attach_info.draw(layout)
                    layout.operator("view3d.pick_workplane", text="", icon='SNAP_NORMAL')
                
                with layout.row(True):
                    layout.prop(self, "plane_pos", text="X", index=0)
                    layout.prop(self, "plane_rot", text="Pitch", index=0)
                with layout.row(True):
                    layout.prop(self, "plane_pos", text="Y", index=1)
                    layout.prop(self, "plane_rot", text="Yaw", index=1)
                with layout.row(True):
                    layout.prop(self, "plane_pos", text="Z", index=2)
                    layout.prop(self, "plane_rot", text="Roll", index=2)
            
            with layout.column(True):
                with layout.row(True):
                    layout.prop(self, "snap_to_cartesian", text="", icon='GRID')
                    layout.prop(self, "scale", text="Scale")
                with layout.row(True):
                    layout.prop(self, "snap_to_polar", text="", icon='FREEZE')
                    layout.prop(self, "polar_subdivs", text="Angles")
                with layout.row(True):
                    layout.prop(self, "snap_to_plane", text="", icon='MESH_PLANE')
                    layout.prop(self, "limit", text="Limit")
    
    @addon.view3d_draw('POST_VIEW')
    def draw_view():
        context = bpy.context
        tfm_tools = get_transform_tools(context)
        self = tfm_tools.workplane
        if not self.snap_any: return
        
        rv3d_context = UIMonitor.last_rv3d_context
        if not rv3d_context: return
        region_data = rv3d_context.get("region_data")
        if region_data != context.region_data: return
        space_data = rv3d_context.get("space_data")
        if space_data.show_only_render: return
        
        workplane_obj = self.work_obj_get(self.workplane_name)
        if not workplane_obj: return
        
        self.align_to_view()
        
        m = workplane_obj.matrix_world
        
        scale = self.scale
        
        view_pos = self.view_pos
        visible_radius = scale * self.max_grid_ivdist * 0.5
        stepsize = scale
        z_offset = 0.0#01
        
        prefs = addon.preferences
        c_WP = prefs.workplane_color
        c_LS = prefs.workplane_lines_color
        c_LS10 = prefs.workplane_lines10_color
        stipple = (prefs.workplane_stipple, 21845) # 21845 = 101010101010101
        
        if self.limit == 0:
            def drawline(p0, p1, is10=False):
                p0 = m * p0
                p1 = m * p1
                intersect = mathutils.geometry.intersect_line_sphere(p0, p1, view_pos, visible_radius, False)
                if not intersect: return
                pA, pB = intersect
                if (not pA) or (not pB): return
                pd = (p1 - p0).normalized()
                tA = max((pA - p0).dot(pd), 0.0)
                tB = max((pB - p0).dot(pd), 0.0)
                pA = p0 + pd * tA
                pB = p0 + pd * tB
                _c_LS = (c_LS10 if is10 else c_LS)
                with cgl.batch('LINE_STRIP') as batch:
                    p0 = pA
                    cgl.Color = (_c_LS[0], _c_LS[1], _c_LS[2], _c_LS[3] * (1.0 - (p0-view_pos).magnitude/visible_radius))
                    batch.vertex(*p0)
                    n = 2 # int((pA-pB).magnitude / stepsize)+1
                    for i in range(n+1):
                        p1 = pA.lerp(pB, (i/n))
                        cgl.Color = (_c_LS[0], _c_LS[1], _c_LS[2], _c_LS[3] * (1.0 - (p1-view_pos).magnitude/visible_radius))
                        batch.vertex(*p1)
                        p0 = p1
        else:
            def drawline(p0, p1, is10=False):
                p0 = m * p0
                p1 = m * p1
                _c_LS = (c_LS10 if is10 else c_LS)
                with cgl.batch('LINE_STRIP') as batch:
                    cgl.Color = (_c_LS[0], _c_LS[1], _c_LS[2], _c_LS[3])
                    batch.vertex(*p0)
                    batch.vertex(*p1)
        
        if self.snap_to_polar or self.snap_to_cartesian:
            with cgl(DepthRange=(0, 1-(1e-7)), LineWidth=1, LineStipple=stipple, DepthMask=0, DEPTH_TEST=True, BLEND=True, LINE_STIPPLE=True, ShadeModel='SMOOTH'):
                if self.snap_to_polar:
                    n = self.polar_subdivs
                    for i in range(n):
                        w = (i/n) * math.pi * 2
                        pd = Vector((math.sin(w), math.cos(w)))
                        if self.limit != 0:
                            pd *= ((self.limit * scale) / max(abs(pd.x), abs(pd.y)))
                        p0 = Vector((0.0, 0.0, z_offset))
                        p1 = Vector((pd.x, pd.y, z_offset))
                        drawline(p0, p1)
                
                if self.snap_to_cartesian:
                    center = Vector(self.view_ixy).to_3d() * scale
                    if self.limit == 0:
                        n = int(visible_radius / scale) + 1
                        cb = visible_radius
                    else:
                        n = self.limit - 1
                        cb = self.limit * scale
                    for i in range(-n, n+1):
                        ca = i * scale
                        p0 = center + Vector((ca, -cb, z_offset))
                        p1 = center + Vector((ca, cb, z_offset))
                        drawline(p0, p1, (((self.view_ixy[0]+i) % 10) == 0))
                        p0 = center + Vector((-cb, ca, z_offset))
                        p1 = center + Vector((cb, ca, z_offset))
                        drawline(p0, p1, (((self.view_ixy[1]+i) % 10) == 0))
        
        with cgl(DepthRange=(0, 1-(1e-7)), DepthMask=0, DEPTH_TEST=True, BLEND=True, ShadeModel='SMOOTH'):
            with cgl.batch('TRIANGLE_FAN') as batch:
                if self.limit == 0:
                    center = Vector(self.view_xy).to_3d()
                    max_dist = self.view_range * 0.5
                    cgl.Color = (c_WP[0], c_WP[1], c_WP[2], c_WP[3])
                    batch.vertex(*(m * (center + Vector((0.0, 0.0, z_offset)))))
                    cgl.Color = (c_WP[0], c_WP[1], c_WP[2], 0.0)
                    n = 16
                    for i in range(n+1):
                        w = (i/n) * math.pi * 2
                        p = Vector((max_dist * math.sin(w), max_dist * math.cos(w), z_offset))
                        batch.vertex(*(m * (center + p)))
                else:
                    center = Vector()
                    max_dist = self.limit * scale
                    cgl.Color = (c_WP[0], c_WP[1], c_WP[2], c_WP[3])
                    batch.vertex(*(m * Vector((-max_dist, -max_dist, z_offset))))
                    batch.vertex(*(m * Vector((-max_dist, max_dist, z_offset))))
                    batch.vertex(*(m * Vector((max_dist, max_dist, z_offset))))
                    batch.vertex(*(m * Vector((max_dist, -max_dist, z_offset))))
    
    del draw_view
    
    def calc_aligned_xyzt(self, view_dir):
        xyzt = self.plane_xyzt
        
        origin = xyzt[3]
        dir_x = xyzt[0]
        dir_y = xyzt[1]
        dir_z = xyzt[2]
        dot_x = abs(view_dir.dot(dir_x))
        dot_y = abs(view_dir.dot(dir_y))
        dot_z = abs(view_dir.dot(dir_z))
        
        axis_choice = 0
        if self.swap_axes:
            if (dot_z >= dot_x) and (dot_z >= dot_y):
                pass # everything already aligned
            elif (dot_y >= dot_x):
                dir_x, dir_y, dir_z = -dir_x, dir_z, -dir_y
                axis_choice = 1
            else:
                dir_x, dir_y, dir_z = dir_y, dir_z, -dir_x
                axis_choice = 2
        
        return origin, dir_x, dir_y, dir_z, axis_choice
    
    def calc_view_range(self, sv, workplane_obj, origin, dir_z):
        view_dir = sv.forward
        view_pos = (sv.viewpoint if sv.is_perspective else sv.focus)
        view_to_origin = view_pos - origin
        view_dist = view_to_origin.dot(dir_z)
        view_proj = view_pos - (dir_z * view_dist)
        
        max_dist = sv.clip_end
        
        rw, rh = sv.region.width, sv.region.height
        rays = [sv.ray((0, 0)), sv.ray((rw, 0)), sv.ray((0, rh)), sv.ray((rw, rh))]
        for ray in rays:
            p = mathutils.geometry.intersect_line_plane(ray[0], ray[1], origin, dir_z)
            if p: max_dist = max(max_dist, (p - origin).magnitude)
        
        wpm = workplane_obj.matrix_world
        pos = matrix_inverted_safe(wpm) * self.view_proj
        ix = int(pos.x / self.scale)
        iy = int(pos.y / self.scale)
        view_ixy = (ix, iy)
        
        max_idist = int(3 * max_dist / self.view_range) # ~arbitrary quantization
        
        self.max_dist = max_dist
        self.view_pos = view_pos
        self.view_proj = view_proj
        self.view_dist = view_dist
        self.view_range = sv.clip_end
        self.view_xy = pos.to_2d()
        
        return max_idist, view_ixy
    
    def align_to_view(self, force=False):
        workplane_obj = self.work_obj_get(self.workplane_name)
        if not workplane_obj: return
        
        rv3d_context = UIMonitor.last_rv3d_context
        if not rv3d_context: return
        
        force |= (not self.matrices_initialized)
        
        sv = SmartView3D(**rv3d_context)
        view_dir = sv.forward
        
        origin, dir_x, dir_y, dir_z, axis_choice = self.calc_aligned_xyzt(view_dir)
        
        if force or (axis_choice != self.last_axis_choice):
            self.last_axis_choice = axis_choice
            workplane_obj.matrix_world = matrix_compose(dir_x, dir_y, dir_z, origin)
            force = True # other workobjects must be realigned
        
        max_idist, view_ixy = self.calc_view_range(sv, workplane_obj, origin, dir_z)
        
        if self.limit != 0:
            max_idist = -self.limit # make sure it won't intersect with "unlimited" values
            view_ixy = (0, 0)
            worksurf_scale = self.limit * self.scale
        else:
            worksurf_scale = self.max_dist * 5
        
        if force or (max_idist != self.max_idist):
            self.max_idist = max_idist
            scale = worksurf_scale
            worksurf_obj = self.work_obj_get(self.worksurf_name)
            if worksurf_obj:
                worksurf_obj.matrix_world = matrix_compose(dir_x*scale, dir_y*scale, dir_z*scale, origin)
            workpolar_obj = self.work_obj_get(self.workpolar_name)
            if workpolar_obj:
                workpolar_obj.matrix_world = worksurf_obj.matrix_world # manually update to avoid 1-frame lag
        
        if force or (view_ixy != tuple(self.view_ixy)):
            self.view_ixy = view_ixy
            workgrid_obj = self.work_obj_get(self.workgrid_name)
            if workgrid_obj:
                offset = self.scale * ((dir_x * self.view_ixy[0]) + (dir_y * self.view_ixy[1]))
                workgrid_obj.matrix_world = matrix_compose(dir_x, dir_y, dir_z, origin+offset)
        
        if not self.matrices_initialized: self.matrices_initialized = True # avoid unnecessary UI updates
    
    def detect_view_alignment(self):
        if not self.snap_any: return
        
        rv3d_context = UIMonitor.last_rv3d_context
        if not rv3d_context: return
        
        sv = SmartView3D(**rv3d_context)
        if not sv: return
        
        cls = WorkplanePG
        
        region = hash(sv.region) # just for comparison
        region_rot = sv.forward # just for comparison
        
        if cls.forced_view_alignment:
            cls.prev_region = None
            cls.prev_region_rot = None
            is_aligned = True
        else:
            if cls.prev_region != region:
                cls.prev_region = region
                cls.prev_region_rot = None
            
            rotated = False
            if region_rot != cls.prev_region_rot:
                if cls.prev_region_rot: rotated = True
                cls.prev_region_rot = region_rot
            
            """
            epsilon = 1e-5
            
            xyzt = self.plane_xyzt
            
            dot_min = 1.0
            for view_dir in (sv.forward, sv.up):
                dot_x = abs(xyzt[0].dot(view_dir))
                dot_y = abs(xyzt[1].dot(view_dir))
                dot_z = abs(xyzt[2].dot(view_dir))
                dot_max = max(dot_x, dot_y, dot_z)
                dot_min = min(dot_min, dot_max)
            
            is_aligned = (abs(1 - dot_min) < epsilon)
            """
            
            is_aligned = not rotated
        
        is_unaligned = not is_aligned
        
        if (not cls.forced_view_alignment) and is_aligned: return # don't switch back
        
        prefs = bpy.context.user_preferences
        if prefs.view.use_auto_perspective:
            if is_unaligned != sv.is_perspective:
                sv.is_perspective = is_unaligned
        
        if addon.preferences.auto_align_objects:
            if is_unaligned != self.use_world:
                self.use_world = is_unaligned
    
    def update_attachment_matrix(self):
        old_exists, old_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        new_exists, new_matrix = self.attach_info.calc_matrix()
        if (new_matrix == old_matrix): return
        
        if new_exists == old_exists:
            self.attach_info.matrix = new_matrix
            self.attach_info.matrix_exists = new_exists
            self.align_to_view(True)
        else:
            xyzt = self.plane_xyzt
            self.attach_info.matrix = new_matrix
            self.attach_info.matrix_exists = new_exists
            self.plane_xyzt = xyzt
    
    def on_scene_update(self):
        self.update_attachment_matrix()
        
        if self.snap_any:
            self.ensure_workplane_objs(True)
            self.detect_view_alignment()
        else:
            self.delete_workplane_objs()
    
    def on_unregister(self):
        self.delete_workplane_objs()
        self.block_navigation_operators(False)
    
    def on_ui_monitor(self, context, event):
        pass

@addon.Operator(idname="view3d.pick_workplane", options={'BLOCKING'}, description=
"Pick workplane")
class Operator_Pick_Workplane:
    def invoke(self, context, event):
        tfm_tools = get_transform_tools(context)
        workplane = tfm_tools.workplane
        
        self.snap_to_plane = workplane.snap_to_plane
        self.snap_to_cartesian = workplane.snap_to_cartesian
        self.snap_to_polar = workplane.snap_to_polar
        if not workplane.snap_any: workplane.snap_to_cartesian = True
        
        self.obj_name = workplane.attach_info.obj_name
        self.attach_matrix = workplane.attach_info.matrix
        
        work_objs = set(workplane.get_workplane_objs())
        
        self.xyzt = workplane.plane_xyzt
        
        self.swap_axes = workplane.swap_axes
        workplane.swap_axes = False
        
        scene = context.scene
        self.scene = scene
        
        raycastable_objects = []
        for obj in scene.objects:
            if obj.type != 'MESH': continue
            if not obj.is_visible(scene): continue
            if obj in work_objs: continue
            raycastable_objects.append((obj, matrix_inverted_safe(obj.matrix_world)))
        self.raycastable_objects = raycastable_objects
        
        UIMonitor.update(context, event)
        
        #context.window.cursor_modal_set('EYEDROPPER')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def ray_cast(self, ray):
        for obj, m_inv in self.raycastable_objects:
            try:
                result = obj.ray_cast(m_inv * ray[0], m_inv * ray[1])
            except RuntimeError: # e.g. meshes in edit mode
                continue
            
            if result and (result[2] >= 0):
                m = obj.matrix_world
                
                p0 = result[0]
                n0 = result[1]
                
                p = m * p0
                
                x, y, z = orthogonal_XYZ(None, None, n0)
                px = m * (p0 + x)
                py = m * (p0 + y)
                x = px - p
                y = py - p
                n = x.cross(y)
                n.normalize()
                
                return (True, obj, m, p, n)
        
        return (False, None, Matrix(), Vector(), Vector())
    
    def modal(self, context, event):
        UIMonitor.update(context, event)
        
        cancel = (event.type in {'ESC', 'RIGHTMOUSE'})
        confirm = (event.type == 'LEFTMOUSE') and (event.value == 'PRESS')
        
        mouse = Vector((event.mouse_x, event.mouse_y))
        
        raycast_result = None
        sv = SmartView3D((mouse.x, mouse.y, 0))
        if sv:
            ray = sv.ray(mouse, coords='WINDOW')
            raycast_result = self.ray_cast(ray)
            depthcast_result = sv.depth_cast(mouse, coords='WINDOW')
            if raycast_result[0] and depthcast_result[0]:
                rl = (raycast_result[-2] - ray[0]).magnitude
                dl = (depthcast_result[-2] - ray[0]).magnitude
                epsilon = 1e-2
                if (rl - dl) > rl*epsilon: raycast_result = depthcast_result
                #if raycast_result[4].magnitude < 0.5:
                #    raycast_result = list(raycast_result)
                #    raycast_result[4] = depthcast_result[4]
            elif depthcast_result[0]:
                raycast_result = depthcast_result
        
        tfm_tools = get_transform_tools(context)
        workplane = tfm_tools.workplane
        
        if raycast_result and raycast_result[0]:
            x, y, z = orthogonal_XYZ(None, None, raycast_result[4], "z")
            t = raycast_result[3]
            obj = raycast_result[1]
            workplane.attach_info.obj_name = (obj.name if obj else "")
            workplane.plane_xyzt = (x, y, z, t)
        
        if cancel or confirm:
            if cancel:
                workplane.snap_to_plane = self.snap_to_plane
                workplane.snap_to_cartesian = self.snap_to_cartesian
                workplane.snap_to_polar = self.snap_to_polar
                workplane.attach_info.obj_name = self.obj_name
                workplane.attach_info.matrix = self.attach_matrix
                workplane.plane_xyzt = self.xyzt
            workplane.swap_axes = self.swap_axes
            #context.window.cursor_modal_restore()
            return ({'FINISHED'} if confirm else {'CANCELLED'})
        return {'RUNNING_MODAL'}

@addon.Operator(idname="view3d.snap_cursor_workplane", options={'BLOCKING'}, description=
"Click: snap cursor to workplane origin, Ctrl+Click: snap workplane to cursor")
def Operator_Snap_Cursor_Workplane(self, context, event):
    tfm_tools = get_transform_tools(context)
    workplane = tfm_tools.workplane
    
    xyzt = workplane.plane_xyzt
    if event and event.ctrl:
        workplane.plane_xyzt = (xyzt[0], xyzt[1], xyzt[2], BlUtil.Scene.cursor(context))
    else:
        BlUtil.Scene.cursor_set(context, xyzt[3])

@addon.Operator(idname="view3d.align_objects_to_workplane", options={'REGISTER', 'UNDO'}, description=
"Click: align object(s) to workplane", mode='OBJECT')
def Operator_Align_Objects_To_Workplane(self, context, event):
    tfm_tools = get_transform_tools(context)
    workplane = tfm_tools.workplane
    
    workplane_obj = workplane.work_obj_get(workplane.workplane_name)
    if not workplane_obj: return {'CANCELLED'}
    
    if context.mode != 'OBJECT': return {'CANCELLED'}
    
    def m2xyz(m):
        return m.col[0].to_3d().normalized(), m.col[1].to_3d().normalized(), m.col[2].to_3d().normalized()
    
    m = Matrix(workplane_obj.matrix_world)
    w_xyz = m2xyz(m)
    
    for obj, select_names in Selection(context):
        om = obj.matrix_world
        om3 = om.to_3x3()
        o_xyz = m2xyz(om)
        
        processed = []
        while len(processed) < 2:
            best_dot = -2.0
            best_o = None
            best_w = None
            for i_o in (0, 1, 2):
                if i_o in processed: continue
                for i_w in (0, 1, 2):
                    dot = abs(o_xyz[i_o].dot(w_xyz[i_w]))
                    if dot > best_dot:
                        best_dot = dot
                        best_o = i_o
                        best_w = i_w
            processed.append(best_o)
            best_o = o_xyz[best_o]
            best_w = w_xyz[best_w]
            if best_o.dot(best_w) < 0: best_w = -best_w
            print((best_o, best_w))
            q = best_o.rotation_difference(best_w)
            o_xyz = (q * o_xyz[0], q * o_xyz[1], q * o_xyz[2])
            om3.rotate(q) # 4x4 matrix cannot be rotated
        
        obj.matrix_world = matrix_compose(om3.col[0], om3.col[1], om3.col[2], om.translation)

@addon.Operator(idname="view3d.view_all_workplane", options={'INTERNAL', 'BLOCKING'}, description="View all")
class Operator_View_All_Workplane:
    use_all_regions = False | prop()
    center = False | prop()
    
    def invoke(self, context, event):
        tfm_tools = get_transform_tools(context)
        workplane = tfm_tools.workplane
        workplane_obj = workplane.work_obj_get(workplane.workplane_name)
        if not workplane_obj: return {'CANCELLED'}
        
        svs = {}
        if not self.use_all_regions:
            rv3d_context = UIMonitor.last_rv3d_context
            if rv3d_context:
                sv = SmartView3D(context, **rv3d_context)
                if sv: svs[sv] = {}
        else:
            for sv in SmartView3D.find_in_ui(context.window):
                if sv: svs[sv] = {}
        
        if not svs: return {'CANCELLED'}
        self.svs = svs
        
        bbox_min, bbox_max = BlUtil.Scene.bounding_box(context.scene, exclude=workplane.workobj_names)
        if bbox_min is None: bbox_min, bbox_max = Vector(), Vector()
        
        if self.center:
            bbox_min = Vector((min(bbox_min.x, 0), min(bbox_min.y, 0), min(bbox_min.z, 0)))
            bbox_max = Vector((max(bbox_max.x, 0), max(bbox_max.y, 0), max(bbox_max.z, 0)))
        
        center = (bbox_max + bbox_min) * 0.5
        extents = (bbox_max - bbox_min) * 0.5
        
        prefs = context.user_preferences
        
        distance_factor = 1.7
        
        for sv, sv_data in self.svs.items():
            sv_data["pivot0"] = sv.focus
            sv_data["distance0"] = sv.distance
            sv_data["pivot1"] = center
            sv_data["distance1"] = max(extents.magnitude, sv.clip_start) * distance_factor
        
        self.duration = prefs.view.smooth_view / 1000.0
        self.time0 = time.clock()
        self.time1 = self.time0 + self.duration
        
        UIMonitor.update(context, event)
        
        addon.timer_add(0.05, owner=self)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        UIMonitor.update(context, event)
        
        t = min((time.clock() - self.time0) / self.duration, 1.0)
        
        for sv, sv_data in self.svs.items():
            sv.focus = sv_data["pivot0"].lerp(sv_data["pivot1"], t)
            sv.distance = lerp(sv_data["distance0"], sv_data["distance1"], t)
        
        tag_redraw()
        
        if t >= 1:
            addon.remove_matches(owner=self)
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}

@addon.Operator(idname="view3d.orbit_around_workplane", options={'INTERNAL', 'BLOCKING'}, description=
"Orbit around workplane")
class Operator_Orbit_Around_Workplane:
    mode = 'ORBITUP' | prop(items=['ORBITLEFT', 'ORBITRIGHT', 'ORBITUP', 'ORBITDOWN'])
    
    def invoke(self, context, event):
        UIMonitor.update(context, event)
        
        rv3d_context = UIMonitor.last_rv3d_context # can be None
        self.sv = (SmartView3D(**rv3d_context) if rv3d_context else SmartView3D(context))
        if not self.sv: return {'CANCELLED'}
        
        tfm_tools = get_transform_tools(context)
        workplane = tfm_tools.workplane
        workplane_obj = workplane.work_obj_get(workplane.workplane_name)
        if not workplane_obj: return {'CANCELLED'}
        
        prefs = bpy.context.user_preferences
        
        self.sv.use_camera_axes = True
        
        if self.mode == 'ORBITLEFT':
            axis = -workplane.plane_xyzt[2]
        elif self.mode == 'ORBITRIGHT':
            axis = workplane.plane_xyzt[2]
        if self.mode == 'ORBITUP':
            axis = self.sv.left # this is how built-in operator works
        elif self.mode == 'ORBITDOWN':
            axis = self.sv.right # this is how built-in operator works
        angle = math.radians(prefs.view.rotation_angle)
        
        sv.rotation = Quaternion(axis, angle) * sv.rotation # error - for test
        #self.sv.rotation = Quaternion(axis, angle) * self.sv.rotation
        
        return {'FINISHED'}

@addon.Operator(idname="view3d.align_view_to_workplane", options={'INTERNAL', 'BLOCKING'}, description=
"Align view to workplane")
class Operator_Align_View_To_Workplane:
    mode = 'CLOSEST' | prop(items=['LEFT', 'RIGHT', 'BOTTOM', 'TOP', 'FRONT', 'BACK', 'CLOSEST'])
    
    def invoke(self, context, event):
        UIMonitor.update(context, event)
        
        rv3d_context = UIMonitor.last_rv3d_context # can be None
        self.sv = (SmartView3D(**rv3d_context) if rv3d_context else SmartView3D(context))
        if not self.sv: return {'CANCELLED'}
        
        tfm_tools = get_transform_tools(context)
        workplane = tfm_tools.workplane
        workplane_obj = workplane.work_obj_get(workplane.workplane_name)
        if not workplane_obj: return {'CANCELLED'}
        
        prefs = bpy.context.user_preferences
        
        self.sv.use_camera_axes = True
        
        def m2xyz(m):
            return m.col[0].to_3d().normalized(), m.col[1].to_3d().normalized(), m.col[2].to_3d().normalized()
        
        xyzt = workplane.plane_xyzt
        
        if self.mode == 'CLOSEST':
            m = Matrix(workplane_obj.matrix_world)
            m_x, m_y, m_z = m2xyz(m)
            view_fwd = self.sv.forward
            view_up = self.sv.up
            goal_z = -m_z * (-1.0 if m_z.dot(view_fwd) < 0 else 1.0)
            dot_x = m_x.dot(view_up)
            dot_y = m_y.dot(view_up)
            if abs(dot_x) > abs(dot_y):
                goal_y = m_x * (-1.0 if dot_x < 0 else 1.0)
            else:
                goal_y = m_y * (-1.0 if dot_y < 0 else 1.0)
            goal_x = goal_y.cross(goal_z)
        elif self.mode == 'TOP':
            goal_x = xyzt[0]
            goal_y = xyzt[1]
            goal_z = xyzt[2]
        elif self.mode == 'BOTTOM':
            goal_x = xyzt[0]
            goal_y = -xyzt[1]
            goal_z = -xyzt[2]
        elif self.mode == 'FRONT':
            goal_x = xyzt[0]
            goal_y = xyzt[2]
            goal_z = -xyzt[1]
        elif self.mode == 'BACK':
            goal_x = -xyzt[0]
            goal_y = xyzt[2]
            goal_z = xyzt[1]
        elif self.mode == 'RIGHT':
            goal_x = xyzt[1]
            goal_y = xyzt[2]
            goal_z = xyzt[0]
        elif self.mode == 'LEFT':
            goal_x = -xyzt[1]
            goal_y = xyzt[2]
            goal_z = -xyzt[0]
        
        if prefs.view.use_auto_perspective:
            self.sv.is_perspective = False
            WorkplanePG.forced_view_alignment = True
        
        self.use_viewpoint = (self.sv.is_perspective) and (self.mode == 'CLOSEST')
        
        if self.use_viewpoint:
            pivot = self.sv.viewpoint
            distance = goal_z.dot(pivot - xyzt[3])
            clamped_distance = max(distance, self.sv.clip_start*2)
            
            self.pivot = pivot
            self.pivot1 = pivot - goal_z*(distance - clamped_distance)
            self.sv.distance = clamped_distance # this moves the viewpoint
            self.sv.viewpoint = pivot # restore the viewpoint
        else:
            pivot = self.sv.focus
            distance = goal_z.dot(pivot - xyzt[3])
            
            self.pivot = pivot
            self.pivot1 = pivot - goal_z*distance
        
        self.rot0 = self.sv.rotation
        self.rot1 = matrix_compose(goal_x, goal_y, goal_z).to_quaternion()
        
        self.duration = prefs.view.smooth_view / 1000.0
        self.time0 = time.clock()
        self.time1 = self.time0 + self.duration
        
        addon.timer_add(0.05, owner=self)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def project_cursor(self, context):
        cursor_pos = BlUtil.Scene.cursor(context)
        xy = self.sv.project(cursor_pos)
        if not xy: return
        cursor_pos = self.sv.unproject(xy)
        BlUtil.Scene.cursor_set(context, cursor_pos)
    
    def modal(self, context, event):
        UIMonitor.update(context, event)
        
        t = min((time.clock() - self.time0) / self.duration, 1.0)
        
        self.sv.rotation = self.rot0.slerp(self.rot1, t)
        if self.use_viewpoint:
            self.sv.viewpoint = self.pivot.lerp(self.pivot1, t)
        else:
            self.sv.focus = self.pivot.lerp(self.pivot1, t)
        
        tag_redraw()
        
        if t >= 1:
            WorkplanePG.forced_view_alignment = False
            self.project_cursor(context)
            addon.remove_matches(owner=self)
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}

@addon.Menu(label="Mode")
class VIEW3D_PIE_bbox_transform_mode:
    def draw(self, context):
        layout = self.layout
        pie = layout.menu_pie()
        pie.operator_context = 'INVOKE_REGION_WIN' # is this necessary?
        pie.operator("view3d.bbox_transform_execute", text="Scale", icon='MAN_SCALE').mode = 'SCALE'
        pie.operator("view3d.bbox_transform_execute", text="Rotate", icon='MAN_ROT').mode = 'ROTATE'

@addon.Operator(idname="view3d.bbox_transform_execute", options={'BLOCKING'}, description=
"Execute Bounding Box Transform")
class Operator_BBox_Transform_Execute:
    mode = 'SCALE' | prop(items=[('SCALE', "Scale"), ('ROTATE', "Rotate")])
    
    constraint_axis = (False, False, False)
    cursor_location = Vector()
    old_cursor_location = Vector()
    
    def invoke(self, context, event):
        v3d = context.space_data
        ts = context.tool_settings
        
        old_cursor_location = Vector(self.old_cursor_location)
        old_pivot_point = v3d.pivot_point
        def restore_pivot(*args):
            v3d.cursor_location = old_cursor_location
            v3d.pivot_point = old_pivot_point
        UIMonitor.on_next_update.append(restore_pivot)
        
        v3d.cursor_location = Vector(self.cursor_location)
        v3d.pivot_point = 'CURSOR'
        
        execution_context = 'INVOKE_REGION_WIN' # INVOKE_DEFAULT seems to not work as expected here
        op_args = dict(
            constraint_axis=self.constraint_axis,
            constraint_orientation=v3d.transform_orientation,
            proportional=ts.proportional_edit,
            proportional_edit_falloff=ts.proportional_edit_falloff,
            proportional_size=ts.proportional_size,
        )
        
        if self.mode == 'SCALE':
            return bpy.ops.transform.resize(execution_context, **op_args)
        else:
            return bpy.ops.transform.rotate(execution_context, **op_args)

@addon.Operator(idname="view3d.bbox_transform", options={'BLOCKING'}, description=
"Bounding Box Transform")
class Operator_BBox_Transform:
    mode = 'SCALE' | prop(items=[('SCALE', "Scale"), ('ROTATE', "Rotate")])
    coordsystem = 'MANIPULATOR' | prop()
    
    lines_template = [
        ((0,0,0), (1,0,0)),
        ((1,0,0), (1,1,0)),
        ((1,1,0), (0,1,0)),
        ((0,1,0), (0,0,0)),
        
        ((0,0,1), (1,0,1)),
        ((1,0,1), (1,1,1)),
        ((1,1,1), (0,1,1)),
        ((0,1,1), (0,0,1)),
        
        ((0,0,0), (0,0,1)),
        ((1,0,0), (1,0,1)),
        ((1,1,0), (1,1,1)),
        ((0,1,0), (0,1,1)),
    ]
    
    def invoke(self, context, event):
        csm = CoordSystemMatrix(self.coordsystem, context=context)
        self.matrix = csm.final_matrix()
        self.bbox = BlUtil.Selection.bounding_box(context, self.matrix)
        self.bbox_origin = self.bbox[0]
        self.bbox_delta = ((self.bbox[1] - self.bbox[0]) if self.bbox[0] is not None else Vector())
        if max(self.bbox_delta) < 1e-6: return {'CANCELLED'}
        
        m = self.matrix
        m3 = m.to_3x3()
        self.origin = m * self.bbox_origin
        self.dir_x = m3 * Vector((self.bbox_delta.x, 0, 0))
        self.dir_y = m3 * Vector((0, self.bbox_delta.y, 0))
        self.dir_z = m3 * Vector((0, 0, self.bbox_delta.z))
        self.pm = matrix_compose(self.dir_x, self.dir_y, self.dir_z, self.origin)
        self.pm_inv = matrix_inverted_safe(self.pm)
        
        self.reaction_distance = 5.0
        self.search_result = (0,0,0)
        self.line_proj = None
        
        def int_round_vector(v):
            return (int(round(v.x)), int(round(v.y)), int(round(v.z)))
        
        self.points = []
        for iz in (0.0, 1.0):
            for iy in (0.0, 1.0):
                for ix in (0.0, 1.0):
                    p = (ix, iy, iz)
                    n = (ix*2-1, iy*2-1, iz*2-1)
                    p_abs = self.getpoint(p)
                    self.points.append((p, n, p_abs))
        
        for i in (0, 1, 2):
            for s in (-1, 1):
                n = Vector()
                n[i] = s
                p = Vector((0.5, 0.5, 0.5)) + (n * 0.5)
                n = int_round_vector(n)
                p_abs = self.getpoint(p)
                self.points.append((p, n, p_abs))
        
        self.lines = []
        for p0, p1 in self.lines_template:
            pmid = (Vector(p0) + Vector(p1)) * 0.5
            pd = (pmid - Vector((0.5, 0.5, 0.5)))*2
            n = int_round_vector(pd)
            p0_abs = self.getpoint(p0)
            p1_abs = self.getpoint(p1)
            self.lines.append((p0, p1, n, p0_abs, p1_abs))
        
        v3d_regions = []
        v3d_spaces = {}
        for area in context.screen.areas:
            if area.type != 'VIEW_3D': continue
            v3d_regions.extend(region for region in area.regions if region.type == 'WINDOW')
            for space in area.spaces:
                if space.type != 'VIEW_3D': continue
                v3d_spaces[space] = dict(
                    show_manipulator = space.show_manipulator,
                    cursor_location = Vector(space.cursor_location), # e.g. if it's in the Local View mode
                )
                space.show_manipulator = False
        self.v3d_spaces = v3d_spaces
        self.v3d_regions = v3d_regions
        
        v3d = context.space_data
        v3d.cursor_location = self.getpoint(Vector((0.5, 0.5, 0.5)))
        
        UIMonitor.update(context, event)
        self.update_sv(event)
        
        addon.view3d_draw('POST_VIEW', owner=self)(self.draw_view)
        addon.view3d_draw('POST_PIXEL', owner=self)(self.draw_px)
        context.window_manager.modal_handler_add(self)
        self.tag_redraw()
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        UIMonitor.update(context, event)
        
        if event.value == 'PRESS':
            confirm = (event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'})
            cancel = not confirm
            pass_through = (event.type not in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'ESC', 'RIGHTMOUSE'})
        else:
            confirm = False
            cancel = False
            pass_through = False
        
        if 'MOUSEMOVE' in event.type:
            self.update_sv(event)
            if self.sv:
                v3d = self.sv.space_data
                cp = (Vector((0.5, 0.5, 0.5)) - Vector(self.search_result) * 0.5)
                v3d.cursor_location = self.getpoint(cp)
            self.tag_redraw()
        
        if cancel or confirm:
            addon.remove_matches(owner=self)
            self.restore_states()
            self.tag_redraw()
            
            if confirm and self.sv:
                if event.type == 'LEFTMOUSE': # if pressed Enter, just keep the cursor position
                    v3d = self.sv.space_data
                    ts = context.tool_settings
                    
                    # TODO: instead of standard pie menu, draw a custom one?
                    # (when a menu is invoked, this operator ends, which means bbox is no longer rendered)
                    
                    old_cursor_location = self.v3d_spaces[v3d]["cursor_location"]
                    
                    cp = (Vector((0.5, 0.5, 0.5)) - Vector(self.search_result) * 0.5)
                    new_cursor_location = self.getpoint(cp)
                    
                    """
                    old_pivot_point = v3d.pivot_point
                    def restore_pivot(*args):
                        v3d.cursor_location = old_cursor_location
                        v3d.pivot_point = old_pivot_point
                    UIMonitor.on_next_update.append(restore_pivot)
                    
                    v3d.cursor_location = new_cursor_location
                    v3d.pivot_point = 'CURSOR'
                    """
                    
                    bbox_exec = Operator_BBox_Transform_Execute
                    bbox_exec.constraint_axis = tuple((s != 0) for s in self.search_result)
                    bbox_exec.cursor_location = new_cursor_location
                    bbox_exec.old_cursor_location = old_cursor_location
                    
                    # TODO: 2.70 does not support pie menus!
                    bpy.ops.wm.call_menu_pie('INVOKE_REGION_WIN', name="VIEW3D_PIE_bbox_transform_mode")
                    
                    """
                    constraint_axis = tuple((s != 0) for s in self.search_result)
                    execution_context = 'INVOKE_REGION_WIN' # INVOKE_DEFAULT seems to not work as expected here
                    op_args = dict(
                        constraint_axis=constraint_axis,
                        constraint_orientation=v3d.transform_orientation,
                        proportional=ts.proportional_edit,
                        proportional_edit_falloff=ts.proportional_edit_falloff,
                        proportional_size=ts.proportional_size,
                    )
                    if self.mode == 'SCALE':
                        bpy.ops.transform.resize(execution_context, **op_args)
                    else:
                        bpy.ops.transform.rotate(execution_context, **op_args)
                    """
                
                result = {'FINISHED'}
            else:
                if self.sv:
                    v3d = self.sv.space_data
                    old_cursor_location = self.v3d_spaces[v3d]["cursor_location"]
                    v3d.cursor_location = old_cursor_location
                
                result = ({'CANCELLED', 'PASS_THROUGH'} if pass_through else {'CANCELLED'})
            
            return result
        
        return {'RUNNING_MODAL'}
    
    def getpoint(self, p):
        return self.pm * Vector(p)
    
    def tag_redraw(self):
        for region in self.v3d_regions:
            region.tag_redraw()
    
    def restore_states(self):
        for space, states in self.v3d_spaces.items():
            for k, v in states.items():
                setattr(space, k, v)
    
    def update_sv(self, event):
        self.mouse = Vector((event.mouse_x, event.mouse_y))
        self.sv = SmartView3D((self.mouse.x, self.mouse.y, 0))
        
        self.search_result = (0,0,0)
        self.line_proj = None
        
        if self.sv:
            self.search_points()
            self.search_lines()
    
    def search_points(self):
        sv = self.sv
        mpos = sv.convert_ui_coord(self.mouse, 'WINDOW', 'REGION')
        view_dir = sv.forward
        
        best_dist = float("inf")
        best_n = (0,0,0)
        for p, n, p_abs in self.points:
            xy_proj = sv.project(p_abs)
            if not xy_proj: continue
            if (mpos - xy_proj).magnitude <= self.reaction_distance:
                dist = p_abs.dot(view_dir)
                if dist < best_dist:
                    best_dist = dist
                    best_n = n
        
        self.search_result = best_n
    
    def search_lines(self):
        if self.search_result != (0,0,0): return
        sv = self.sv
        mpos = sv.convert_ui_coord(self.mouse, 'WINDOW', 'REGION')
        view_dir = sv.forward
        
        def dist_to_segment_2d(p, a, b):
            l2 = (b - a).length_squared
            if l2 == 0.0: return (p - a).magnitude
            t = min(max((p - a).dot(b - a) / l2, 0.0), 1.0)
            return (a.lerp(b, t) - p).magnitude
        
        best_dist = float("inf")
        best_n = (0,0,0)
        for p0, p1, n, p0_abs, p1_abs in self.lines:
            if view_dir.dot(p1_abs) < view_dir.dot(p0_abs): p0_abs, p1_abs = p1_abs, p0_abs
            
            # make sure we deal with the "visible" part of the line
            plane_near = sv.z_plane(0)
            p_near = mathutils.geometry.intersect_line_plane(p0_abs, p1_abs, plane_near[0], plane_near[1])
            if p_near: # TODO: sv.clip(line/polygon) - returns clipped line/polygon ?
                pd_abs = p1_abs - p0_abs
                t = ((p_near - p0_abs).normalized()).dot(pd_abs.normalized())
                if (t >= 0) and (t <= 1):
                    p0_abs = p0_abs + pd_abs * t
            
            xy0_proj = sv.project(p0_abs)
            if not xy0_proj: continue
            xy1_proj = sv.project(p1_abs)
            if not xy1_proj: continue
            
            if dist_to_segment_2d(mpos, xy0_proj, xy1_proj) <= self.reaction_distance:
                dist = p0_abs.dot(view_dir)
                if dist < best_dist:
                    best_dist = dist
                    best_n = n
                    self.line_proj = (xy0_proj, xy1_proj)
        
        self.search_result = best_n
    
    def draw_view(self):
        prefs = addon.preferences
        c_WP = prefs.workplane_color
        c_LS = prefs.workplane_lines10_color
        
        def drawline(batch, p0, p1):
            batch.vertex(*self.getpoint(p0))
            batch.vertex(*self.getpoint(p1))
        
        def drawquad(batch, p0, p1, p2, p3):
            batch.vertex(*self.getpoint(p0))
            batch.vertex(*self.getpoint(p1))
            batch.vertex(*self.getpoint(p2))
            batch.vertex(*self.getpoint(p0))
            batch.vertex(*self.getpoint(p2))
            batch.vertex(*self.getpoint(p3))
        
        with cgl(DepthMask=0, DEPTH_TEST=True, BLEND=True, CULL_FACE=False):
            cgl.Color = (c_WP[0], c_WP[1], c_WP[2], c_WP[3])
            with cgl.batch('TRIANGLES') as batch:
                drawquad(batch, (0,0,0), (1,0,0), (1,1,0), (0,1,0))
                drawquad(batch, (0,0,1), (1,0,1), (1,1,1), (0,1,1))
                
                drawquad(batch, (0,0,0), (1,0,0), (1,0,1), (0,0,1))
                drawquad(batch, (0,1,0), (1,1,0), (1,1,1), (0,1,1))
                
                drawquad(batch, (0,0,0), (0,1,0), (0,1,1), (0,0,1))
                drawquad(batch, (1,0,0), (1,1,0), (1,1,1), (1,0,1))
        
        with cgl(LineWidth=1, DepthMask=0, DEPTH_TEST=True, BLEND=True, LINE_STIPPLE=True):
            cgl.Color = (c_LS[0], c_LS[1], c_LS[2], c_LS[3])
            with cgl.batch('LINES') as batch:
                for p0, p1, n, p0_abs, p1_abs in self.lines:
                    drawline(batch, p0, p1)
    
    def draw_px(self):
        if not self.sv: return
        sv = self.sv
        
        if bpy.context.region != sv.region: return
        
        cgl.Matrix_ModelView = cgl.Matrix_ModelView_3D
        cgl.Matrix_Projection = cgl.Matrix_Projection_3D
        
        prefs = addon.preferences
        c_WP = prefs.workplane_color
        c_LS = prefs.workplane_lines_color
        
        view_dir = sv.forward
        
        radius = self.reaction_distance
        
        def drawline(batch, p0, p1):
            batch.vertex(*self.getpoint(p0))
            batch.vertex(*self.getpoint(p1))
        
        with cgl(LineWidth=1, DepthMask=0, DEPTH_TEST=False, BLEND=True, LINE_STIPPLE=True):
            cgl.Color = (c_LS[0], c_LS[1], c_LS[2], c_LS[3]*0.35)
            with cgl.batch('LINES') as batch:
                for p0, p1, n, p0_abs, p1_abs in self.lines:
                    drawline(batch, p0, p1)
            
            if self.search_result != (0,0,0):
                cgl.Color = (0.0, 1.0, 0.0, 0.75)
                p0 = (Vector((0.5, 0.5, 0.5)) - Vector(self.search_result) * 0.5)
                p1 = (Vector((0.5, 0.5, 0.5)) + Vector(self.search_result) * 0.5)
                with cgl.batch('LINES') as batch:
                    drawline(batch, p0, p1)
        
        cgl.Matrix_ModelView = cgl.Matrix_ModelView_2D
        cgl.Matrix_Projection = cgl.Matrix_Projection_2D
        
        with cgl(DepthMask=0, DEPTH_TEST=False, BLEND=True):
            for p, n, p_abs in self.points:
                xy_proj = sv.project(p_abs)
                if not xy_proj: continue
                if n == self.search_result:
                    cgl.Color = (0.0, 1.0, 0.0, 0.75)
                else:
                    cgl.Color = (0.5, 0.0, 0.0, 0.75)
                with cgl.batch('POLYGON') as batch:
                    batch.sequence(batch.circle(xy_proj, radius, resolution=16))
            
            for p0, p1, n, p0_abs, p1_abs in self.lines:
                if (n == self.search_result) and self.line_proj:
                    cgl.Color = (0.0, 1.0, 0.0, 0.5)
                    with cgl.batch('POLYGON') as batch:
                        xy0_proj, xy1_proj = self.line_proj
                        xy_n = (xy1_proj - xy0_proj).normalized()
                        if xy_n.magnitude < 0.5: xy_n = Vector((0,1))
                        xy_ort = orthogonal(xy_n)
                        m = Matrix((xy_ort, xy_n))
                        pi2 = math.pi / 2.0
                        for xy in batch.circle((0,0), radius, resolution=16, start=-3*pi2, end=-pi2):
                            batch.vertex(*(m * Vector(xy) + xy0_proj))
                        for xy in batch.circle((0,0), radius, resolution=16, start=-pi2, end=pi2):
                            batch.vertex(*(m * Vector(xy) + xy1_proj))
                    break

@addon.PropertyGroup
class CursorPG:
    def on_attach_update(self, context):
        old_exists, old_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        new_exists, new_matrix = self.attach_info.calc_matrix()
        if (new_matrix == old_matrix): return
        location_world = self.location_world
        self.attach_info.matrix = new_matrix
        self.attach_info.matrix_exists = new_exists
        self.location_world = location_world
    attach_info = make_attach_info("Cursor", ['CS_DISPLAY'], on_attach_update)
    
    attach_location = Vector() | prop()
    
    last_world_pos = Vector((float("nan"), float("nan"), float("nan"))) | prop()
    
    def location_get(self, context, world):
        attachment_exists, attachment_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        if attachment_exists and (not world):
            return Vector(self.attach_location)
        else:
            return BlUtil.Scene.cursor(context)
    
    def location_set(self, context, world, value):
        value = Vector(value)
        attachment_exists, attachment_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        if attachment_exists and (not world):
            self.last_world_pos = attachment_matrix * value
            self.attach_location = value
            BlUtil.Scene.cursor_set(context, self.last_world_pos, False)
        else:
            self.last_world_pos = value
            BlUtil.Scene.cursor_set(context, value, False)
            self.attach_location = matrix_inverted_safe(attachment_matrix) * value
    
    def _get(self):
        return self.location_get(bpy.context, True)
    def _set(self, value):
        self.location_set(bpy.context, True, value)
    location_world = property(_get, _set)
    
    def _get(self):
        return self.location_get(bpy.context, False)
    def _set(self, value):
        self.location_set(bpy.context, False, value)
    location_local = property(_get, _set)
    
    _csm_matrix = None
    def _get(self):
        if ('CS_DISPLAY' in self.attach_info.options):
            m = CoordSystemMatrix.current().final_matrix()
            return matrix_inverted_safe(m) * self.location_world
        else:
            return self.location_local
    def _set(self, value):
        if ('CS_DISPLAY' in self.attach_info.options):
            cls = self.__class__
            if not UIMonitor.user_interaction:
                UIMonitor.user_interaction = True
                m = CoordSystemMatrix.current().final_matrix()
                cls._csm_matrix = m
            else:
                m = cls._csm_matrix or Matrix()
            self.location_world = m * Vector(value)
        else:
            self.location_local = Vector(value)
    location = Vector() | prop(get=_get, set=_set, subtype='TRANSLATION', unit='LENGTH', precision=4) # local / display
    
    history = 0 | prop()
    
    visible = True | prop("WARNING: while cursor is \"invisible\", Blender will endlessly redraw the UI") # or maybe make it an enum? (each method of hiding has its drawbacks)
    hide_method = 'OVERDRAW' | prop(items=[('OVERDRAW', "Overdraw"), ('DISPLACE', "Displace")])
    
    def draw(self, layout):
        title = "3D Cursor"
        with layout.row(True):
            with layout.fold("", ("row", True), False, key=title):
                is_folded = layout.folded
            with layout.row(True)(alignment='LEFT'):
                layout.operator("view3d.transform_tools_cursor_menu", text=title, emboss=False)
            with layout.row()(alignment='RIGHT'):
                with layout.row(True):
                    icon = ('RESTRICT_VIEW_OFF' if self.visible else 'RESTRICT_VIEW_ON')
                    layout.prop(self, "visible", text="", icon=icon)
                    layout.operator("view3d.transform_tools_reset_cursor", text="", icon='LOAD_FACTORY')
        
        if not is_folded:
            with layout.column(True):
                with layout.row(True):
                    self.attach_info.draw(layout)
                    layout.operator("view3d.transform_tools_raycast", text="", icon='SNAP_NORMAL')
                
                layout.prop(self, "location", text="")
    
    @addon.view3d_draw('POST_VIEW')
    def draw_view():
        context = bpy.context
        tfm_tools = get_transform_tools(context)
        self = tfm_tools.cursor
        
        if not self.visible:
            sv = SmartView3D(context)
            v3d = context.space_data
            
            pixelsize = 1
            dpi = context.user_preferences.system.dpi
            widget_unit = (pixelsize * dpi * 20.0 + 36.0) / 72.0
            
            cursor_w = widget_unit*2
            cursor_h = widget_unit*2
            coord = (-cursor_w, -cursor_h)
            
            CursorPG.cursor_save_location = Vector(v3d.cursor_location)
            if sv.is_perspective:
                v3d.cursor_location = sv.viewpoint - (sv.forward * 10)
            else:
                v3d.cursor_location = sv.unproject(coord)
    
    del draw_view
    
    @addon.view3d_draw('POST_PIXEL')
    def draw_px():
        context = bpy.context
        tfm_tools = get_transform_tools(context)
        self = tfm_tools.cursor
        
        if not self.visible:
            v3d = context.space_data
            v3d.cursor_location = CursorPG.cursor_save_location
    
    del draw_px
    
    def update_attachment_matrix(self):
        old_exists, old_matrix = self.attach_info.matrix_exists, self.attach_info.matrix
        new_exists, new_matrix = self.attach_info.calc_matrix()
        
        matrix_changed = (new_matrix != old_matrix) or addons_registry.undo_detected
        
        if not matrix_changed:
            world_pos = BlUtil.Scene.cursor(bpy.context)
            if self.last_world_pos != world_pos: self.location_world = world_pos
        else:
            if new_exists == old_exists:
                location_local = self.location_local
                self.attach_info.matrix = new_matrix
                self.attach_info.matrix_exists = new_exists
                self.location_local = location_local
            else:
                location_world = self.location_world
                self.attach_info.matrix = new_matrix
                self.attach_info.matrix_exists = new_exists
                self.location_world = location_world
    
    def on_scene_update(self):
        self.update_attachment_matrix()

@addon.Operator(idname="view3d.transform_tools_cursor_menu", options={'INTERNAL'}, description=
"Click: Cursor3D menu")
def Operator_Cursor_Menu(self, context, event):
    title = "3D Cursor"
    def draw_popup_menu(self, context):
        tfm_tools = get_transform_tools(context)
        cursor = tfm_tools.cursor
        
        layout = NestedLayout(self.layout)
        
        layout.prop(cursor, "history")
        
        #layout.prop(cursor, "hide_method")
        #layout.prop_menu_enum(cursor, "hide_method", text="Hiding method")
    
    context.window_manager.popup_menu(draw_popup_menu, title="{}".format(title))

@addon.Operator(idname="view3d.transform_tools_reset_cursor", options={'INTERNAL'}, description=
"Click: reset all axes", space_type='VIEW_3D')
def Operator_Reset_Cursor(self, context, event):
    tfm_tools = get_transform_tools(context)
    tfm_tools.cursor.location = Vector()
    return {'FINISHED'}

@addon.PropertyGroup
class RefpointPG:
    id = 0 | prop()
    
    _lock = False
    def _get(self):
        try:
            cluster = BlRna.parent(self)
            refpoints = BlRna.parent(cluster)
        except ValueError: # for some reason this happens sometimes
            return False
        return (tuple(refpoints.active_id) == (cluster.id, self.id))
    def _set(self, value):
        cluster = BlRna.parent(self)
        refpoints = BlRna.parent(cluster)
        if RefpointPG._lock:
            if value: refpoints.active_id = (cluster.id, self.id)
            return
        RefpointPG._lock = True
        if UIMonitor.shift and UIMonitor.ctrl:
            if self.id == 0:
                refpoints.add_cluster(cluster)
            else:
                refpoints.add_cluster(self)
        elif UIMonitor.shift:
            cluster.add_point(self)
        elif UIMonitor.ctrl:
            if self.id == 0:
                refpoints.remove_cluster(cluster)
            else:
                cluster.remove_point(self)
        else:
            if value: refpoints.active_id = (cluster.id, self.id)
        tag_redraw()
        RefpointPG._lock = False
    is_active = False | prop("Click: make active, Shift+Click: copy as sub-point, Shift+Ctrl+Click: copy as new point, Ctrl+Click: delete (sub-)point", get=_get, set=_set)
    
    def on_attach_set(self):
        RefpointPG._location_world_save = self.location_world
    def on_attach_update(self, context):
        self.location_world = RefpointPG._location_world_save
    attach_info = make_attach_info("Reference point", ['CS_DISPLAY', 'CS_ATTACH', 'INHERIT'], on_attach_update, on_attach_set)
    
    attach_info_inherited = property(lambda self: (BlRna.parent(self).points[0] if self.inherit else self).attach_info)
    
    def _get(self):
        return (self.id != 0) and ('INHERIT' in self.attach_info.options)
    def _set(self, value):
        options = self.attach_info.options
        self.attach_info.options = ((options | {'INHERIT'}) if value else (options - {'INHERIT'}))
    inherit = property(_get, _set)
    
    def _get(self):
        if self.id == 0:
            attachment_exists, attachment_matrix = self.attach_info.calc_matrix()
            return attachment_matrix * self.location_local
        else:
            point0 = BlRna.parent(self).points[0]
            if ('INHERIT' in self.attach_info.options):
                attachment_exists, attachment_matrix = point0.attach_info.calc_matrix()
            else:
                attachment_exists, attachment_matrix = self.attach_info.calc_matrix()
            return point0.location_world + attachment_matrix.to_3x3() * self.location_local
    def _set(self, value):
        if self.id == 0:
            attachment_exists, attachment_matrix = self.attach_info.calc_matrix()
            self.location_local = matrix_inverted_safe(attachment_matrix) * Vector(value)
        else:
            point0 = BlRna.parent(self).points[0]
            if ('INHERIT' in self.attach_info.options):
                attachment_exists, attachment_matrix = point0.attach_info.calc_matrix()
            else:
                attachment_exists, attachment_matrix = self.attach_info.calc_matrix()
            value = Vector(value) - point0.location_world
            self.location_local = matrix_inverted_safe(attachment_matrix.to_3x3()) * value
    location_world = property(_get, _set)
    
    location_local = Vector() | prop(update=True) # make sure view is redrawn when location is updated
    
    _csm_matrix = None
    def _get(self):
        if ('CS_DISPLAY' in self.attach_info_inherited.options):
            m = CoordSystemMatrix.current().final_matrix()
            return matrix_inverted_safe(m) * self.location_world
        else:
            return self.location_local
    def _set(self, value):
        if ('CS_DISPLAY' in self.attach_info_inherited.options):
            cls = self.__class__
            if not UIMonitor.user_interaction:
                UIMonitor.user_interaction = True
                m = CoordSystemMatrix.current().final_matrix()
                cls._csm_matrix = m
            else:
                m = cls._csm_matrix or Matrix()
            self.location_world = m * Vector(value)
        else:
            self.location_local = Vector(value)
    location = Vector() | prop(get=_get, set=_set, subtype='TRANSLATION', unit='LENGTH', precision=4) # local / display
    
    def init(self, id, template=None):
        self.id = id
        self.name = RefpointsPG.index_to_name((BlRna.parent(self).id, self.id))
        if template:
            self.attach_info.copy(template.attach_info)
            if (self.id == 0) == (template.id == 0):
                self.location_local = template.location_local
            else:
                self.location_world = template.location_world
        else:
            self.inherit = True
        self.is_active = True
    
    def draw(self, layout):
        with layout.column(True):
            with layout.row(True):
                self.attach_info.draw(layout, self.inherit, self.attach_info_inherited)
                layout.operator("view3d.transform_tools_raycast", text="", icon='SNAP_NORMAL')
            
            layout.prop(self, "location", text="")

@addon.PropertyGroup
class RefpointClusterPG:
    max_points = 10 # this way all indices are no more than one character
    
    id = 0 | prop()
    points = [RefpointPG] | prop()
    
    def init(self, id, template=None):
        self.id = id
        self.name = RefpointsPG.index_to_name(self.id)
        if isinstance(template, RefpointClusterPG) and template.points:
            for i, template_point in enumerate(template.points):
                self.add_point(template_point)
            self.points[0].is_active = True
        else:
            self.add_point(template)
    
    def new_index(self):
        n = len(self.points)
        for i in range(self.max_points):
            if i >= n: return i
            point = self.points[i]
            if point.id != i: return i
        return -1
    
    def add_point(self, template=None):
        point_id = self.new_index()
        if point_id < 0: return None
        point = self.points.add()
        point.init(point_id, template)
        self.points.move(len(self.points)-1, point_id)
        return point
    
    def remove_point(self, point):
        i = binary_search(self.points, point, key=(lambda item: item.id))
        self.points.remove(i)
    
    def draw(self, layout):
        with layout.column(): # this is intentional
            with layout.row(True): # this is intentional
                for point in self.points:
                    layout.row(True)(scale_x=0.1).prop(point, "is_active", text=point.name, toggle=True)
    
    def collect_lines(self, sv, res_lines):
        point0 = self.points[0]
        p0_abs = point0.location_world
        for point in self.points:
            if point.id == 0: continue
            p_abs = point.location_world
            res_lines.append((p0_abs, p_abs))
    
    def collect_points(self, sv, res_points, active_id):
        view_dir = sv.forward
        for point in self.points:
            p_abs = point.location_world
            xy_proj = sv.project(p_abs)
            if not xy_proj: continue
            z_proj = view_dir.dot(point.location_world)
            is_active = (active_id == (self.id, point.id))
            res_points.append((point.name, is_active, xy_proj, z_proj))

@addon.Operator(idname="view3d.transform_tools_refpoints_new_cluster", options={'INTERNAL'}, description="New reference point")
def Operator_Refpoints_New_Cluster(self, context, event):
    tfm_tools = get_transform_tools(context)
    refpoints = tfm_tools.refpoints
    return ({'FINISHED'} if refpoints.add_cluster() else {'CANCELLED'})

@addon.PropertyGroup
class RefpointsPG:
    cluster_names = string.ascii_uppercase
    
    @classmethod
    def index_to_name(cls, id):
        cluster_id, point_id = ((id, -1) if isinstance(id, int) else id)
        if (cluster_id < 0) or (cluster_id >= len(cls.cluster_names)): return ""
        name = cls.cluster_names[cluster_id]
        return (name if point_id <= 0 else name+str(point_id))
    
    @classmethod
    def name_to_index(cls, name):
        if not name: return (-1, -1)
        cluster_id = cls.cluster_names.find(name[0])
        if cluster_id < 0: return (-1, -1)
        try:
            point_id = int(name[1:])
        except ValueError:
            point_id = -1
        point_id = (point_id-1 if point_id >= 0 else -1)
        return (cluster_id, point_id)
    
    dummy_point = RefpointPG | prop()
    
    visible = True | prop()
    
    clusters = [RefpointClusterPG] | prop()
    
    active_id = (-1, -1) | prop()
    
    def _get(self):
        cluster_id, point_id = self.active_id
        i = binary_search(self.clusters, cluster_id, cmp=(lambda item, id: item.id - id))
        if i < 0: return None
        cluster = self.clusters[i]
        i = binary_search(cluster.points, point_id, cmp=(lambda item, id: item.id - id))
        if i < 0: return None
        return cluster.points[i]
    def _set(self, point):
        cluster = BlRna.parent(point)
        self.active_id = (cluster.id, point.id)
    active = property(_get, _set)
    
    def new_index(self):
        n = len(self.clusters)
        for i in range(len(self.cluster_names)):
            if i >= n: return i
            cluster = self.clusters[i]
            if cluster.id != i: return i
        return None
    
    def add_cluster(self, template=None):
        cluster_id = self.new_index()
        if cluster_id < 0: return None
        cluster = self.clusters.add()
        cluster.init(cluster_id, template)
        self.clusters.move(len(self.clusters)-1, cluster_id)
        return cluster
    
    def remove_cluster(self, cluster):
        i = binary_search(self.clusters, cluster, key=(lambda item: item.id))
        self.clusters.remove(i)
    
    def draw(self, layout):
        title = "Refpoints"
        with layout.row(True):
            with layout.fold("", ("row", True), False, key=title):
                is_folded = layout.folded
            with layout.row(True)(alignment='LEFT'):
                layout.label(title)
            with layout.row(True)(alignment='RIGHT'):
                icon = ('RESTRICT_VIEW_OFF' if self.visible else 'RESTRICT_VIEW_ON')
                layout.prop(self, "visible", text="", icon=icon)
        
        if not is_folded:
            active = self.active
            if active:
                active.draw(layout)
            else:
                with layout.column()(enabled=False):
                    self.dummy_point.draw(layout)
            
            if self.clusters:
                with layout.column(True):
                    for cluster in self.clusters:
                        cluster.draw(layout)
            else:
                with layout.row(True)(alignment='LEFT'):
                    layout.operator("view3d.transform_tools_refpoints_new_cluster", text="New", icon='ZOOMIN')
    
    @addon.view3d_draw('POST_PIXEL')
    def draw_px():
        context = bpy.context
        tfm_tools = get_transform_tools(context)
        self = tfm_tools.refpoints
        if not self.visible: return
        
        sv = SmartView3D(context)
        
        cgl.Matrix_ModelView = cgl.Matrix_ModelView_3D
        cgl.Matrix_Projection = cgl.Matrix_Projection_3D
        
        res_lines = []
        for cluster in self.clusters:
            cluster.collect_lines(sv, res_lines)
        
        cgl.Color = (0.0, 0.0, 0.0, 0.75)
        with cgl(LineWidth=1, DepthMask=0, DEPTH_TEST=False, BLEND=True, LINE_STIPPLE=True):
            with cgl.batch('LINES') as batch:
                for line in res_lines:
                    batch.vertex(*line[0])
                    batch.vertex(*line[1])
        
        cgl.Matrix_ModelView = cgl.Matrix_ModelView_2D
        cgl.Matrix_Projection = cgl.Matrix_Projection_2D
        
        active_id = tuple(self.active_id)
        res_points = []
        for cluster in self.clusters:
            cluster.collect_points(sv, res_points, active_id)
        res_points.sort(key=(lambda item: -item[-1]))
        
        radius = 10.0
        with cgl(DepthMask=0, DEPTH_TEST=False, BLEND=True):
            for point_name, is_active, xy_proj, z_proj in res_points:
                cgl.Color = (0.0, 0.0, 0.0, 0.5)
                with cgl.batch('POLYGON') as batch:
                    batch.sequence(batch.circle(xy_proj, radius, resolution=20))
                
                cgl.Color = (0.0, 0.0, 0.0, 1.0)
                with cgl.batch('LINE_STRIP') as batch:
                    batch.sequence(batch.circle(xy_proj, radius, resolution=20))
                
                cgl.Color = ((1.0, 1.0, 0.0, 1.0) if is_active else (1.0, 1.0, 1.0, 1.0))
                cgl.text.draw(point_name, xy_proj, (0.5, 0.5)) # this modifies the BLEND state
                cgl.BLEND = True
    
    del draw_px

@addon.Operator(idname="view3d.transform_tools_snap", options={'REGISTER', 'UNDO'}, description="Click: perform snap/align/match, Shift+Click: show history of commands, Alt+Click: show help")
def Operator_Snap(self, context, event): pass

@addon.Operator(idname="view3d.transform_tools_query", options={'REGISTER', 'UNDO'}, description="Click: perform spatial query, Shift+Click: show history of commands, Alt+Click: show help")
def Operator_Query(self, context, event): pass

@addon.Operator(idname="view3d.transform_tools_raycast", options={'REGISTER', 'UNDO'}, description="Click: snap cursor/plane/point to surface under mouse")
def Operator_Raycast(self, context, event): pass

@addon.PropertyGroup
class TransformToolsPG:
    cursor = CursorPG | prop()
    workplane = WorkplanePG | prop()
    refpoints = RefpointsPG | prop()
    
    command = "" | prop() # Enter: do nothing, Ctrl+Enter: execute as snap, Shift+Enter: execute as spatial query ... OR: interpret by context? (e.g. all queries begin with "?")
    
    active_tools = {'CURSOR'} | prop(items=[('CURSOR', "Cursor", "3D Cursor"), ('WORKPLANE', "Plane", "Workplane"), ('REFPOINTS', "Points", "Reference points")])
    
    def draw_header(self, layout):
        return
        layout.menu("VIEW3D_MT_transform_tools_align", icon='ALIGN', text="")
        layout.menu("VIEW3D_MT_transform_tools_spatial_queries", icon='BORDERMOVE', text="")
    
    def draw(self, layout):
        with layout.row(True):
            layout.operator("view3d.bbox_transform", text="", icon='BBOX')
            layout.prop(self, "command", text="")
            layout.operator("view3d.transform_tools_snap", text="", icon='SNAP_SURFACE')
            layout.operator("view3d.transform_tools_query", text="", icon='BORDERMOVE')
        
        self.cursor.draw(layout)
        self.workplane.draw(layout)
        self.refpoints.draw(layout)

def get_transform_tools(context=None, search=False):
    if context is None: context = bpy.context
    if search: # User Preferences uses a virtual "temp" screen
        wm = context.window_manager
        for window in wm.windows:
            if window.screen.name == "temp": continue
            return window.screen.scene.transform_tools
            #return window.screen.transform_tools
    return context.screen.scene.transform_tools
    #return context.screen.transform_tools
    #return addon.internal.transform_tools

addon.type_extend("Scene", "transform_tools", (TransformToolsPG | prop()))
#addon.type_extend("Screen", "transform_tools", (TransformToolsPG | prop()))
#addon.Internal.transform_tools = TransformToolsPG | prop()

@LeftRightPanel(idname="VIEW3D_PT_transform_tools", space_type='VIEW_3D', category="Transform", label="Transform Tools")
class Panel_Transform_Tools:
    def draw_header(self, context):
        layout = NestedLayout(self.layout)
        get_transform_tools(context).draw_header(layout)
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        get_transform_tools(context).draw(layout)

@addon.scene_update_post
def scene_update(scene):
    context = bpy.context
    tfm_tools = get_transform_tools(context, search=True)
    tfm_tools.workplane.on_scene_update()
    tfm_tools.cursor.on_scene_update()

@addon.on_unregister
def on_unregister():
    context = bpy.context
    tfm_tools = get_transform_tools(context)
    tfm_tools.workplane.on_unregister()

@addon.ui_monitor
def ui_monitor(context, event, UIMonitor):
    context = bpy.context
    tfm_tools = get_transform_tools(context, search=True)
    tfm_tools.workplane.on_ui_monitor(context, event)
