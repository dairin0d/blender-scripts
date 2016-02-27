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

# <pep8 compliant>

bl_info = {
    "name": "Cable Editor",
    "author": "dairin0d, moth3r",
    "version": (0, 5, 1),
    "blender": (2, 7, 0),
    "location": "",
    "description": "Cable editor",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "Object"}
#============================================================================#

if "dairin0d" in locals():
    import imp
    imp.reload(dairin0d)

import bpy

import bmesh

import mathutils
from mathutils import Color, Vector, Matrix, Quaternion, Euler

import math

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_view3d import SmartView3D
from {0}dairin0d.utils_blender import MeshBaker, BlUtil
from {0}dairin0d.utils_math import clamp_angle
from {0}dairin0d.utils_userinput import KeyMapUtils
from {0}dairin0d.utils_ui import NestedLayout, find_ui_area, ui_context_under_coord
from {0}dairin0d.bpy_inspect import prop, BlRna
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

addon = AddonManager()

#============================================================================#

"""
cable editor:
+ add option to scale attachments
+ make children non-selectable by default
+ add operators to duplicate/delete whole hierarchy (also, toggle visibility of cable/all children at once): decide to just add the ability to select whole hierarchy
+ make selectability of children togglable from main cable UI?
+ attachments: assign materials from the main UI
+ auto-twisting: fix start point, fix end point, fix some point in between? twist per length, twist n times
+ check if it's possible to make wires/attachments stay with cable in Local View mode
    * NOTE: when going out of local view, all local-view objects are selected (and made selectable)
+ add Edge Split modifier options for cable
+ add curve fill mode to the Cable panel
+ operator to make cable children non-selectable
  option to actually make curve object hidden (not just wireframe)
  custom wire profile
  option to specify profile/width/height/rotation of individual wires
  multi-row bus cable
  "filled-in" braided cable? (many wires of small size, not just on the outer radius, but everywhere inside)
  multiple layers of wires
+ implement fix for scaling wires
  moth3r asks to implement presets system
  moth3r asks for procedural custom curve profiles
  moth3r suggests to provide the ability to use particles and selected vertices as targets for cables'/wires' ends
  add option for "sides" profile (as seen in the example moth3r showed)

moth3r:
In regards, cable editor, I would like to add an option 'None' to the Half, Full, Side etc. so in that way profile would be turned off for sure. It is also straight forward way to do it.
OR: add a on/off switch for profile (keep radius/extrude in separate vars)
Maybe it would be good to completely separate profile from wires settings. On example, right now Extrude and radius settings are shared in-between. I guess that makes sens but kinda is confusing when you try to figure what is controlling what. 

wires has inverted normals for some guy, but when moth3r opened his file, the normals were correct

add warnings to documentation about issues with scale, default coversion to mesh, joining multiple curves into one object, etc.

For cable systems:
* hub in, hub out (also can be auto-generated?). Hubs can be implemented via armatures (bones with matching names)
* generation rules: adaptor rules, bracket rules, cable rules; weaving rules
* Note: we can use modifiers to transform curves by curves, but they cannot be used to edit derivative curves in-place (even theoretically, this would be quite complicated, since an optimization search would be required)

moth3r calls the following case a "zigzag":
http://ep.yimg.com/ay/directron/black-silverstone-sleeved-3-x-peripheral-4pin-1-x-floppy-4pin-cable-p-n-pp06b-3per10f-5.gif

See this for an example of dealing with hair particles
https://svn.blender.org/svnroot/bf-extensions/contrib/py/scripts/addons/btrace/bTrace.py

https://www.orbolt.com/asset/Dan_Baciu::DB_cable_bundle

http://cgterminal.com/2013/10/05/cinema-4d-tip-using-collision-deformer-to-tape-cables-together/

Some cool (but not priority) ideas:
https://vimeo.com/35145361
"""

# bevel factor mapping does not exit in 2.70
bevel_factor_mapping_exists = ("bevel_factor_mapping_start" in BlRna(bpy.types.Curve).properties)
bevel_factor_mapping_exists &= ("bevel_factor_mapping_end" in BlRna(bpy.types.Curve).properties)

@addon.Panel
class DATA_PT_curve_cable:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"
    bl_label = "Cable"
    
    @classmethod
    def poll(cls, context):
        cable_settings = context.object.cable_settings
        return bool(cable_settings.get_spline())
    
    def draw_header(self, context):
        layout = NestedLayout(self.layout)
        
        cable_settings = context.object.cable_settings
        obj, curve = cable_settings.get_obj_curve()
        
        icon = ('COLOR_GREEN' if cable_settings.is_cable else 'COLOR_RED')
        layout.prop(cable_settings, "is_cable", icon=icon, text="", toggle=True, emboss=False)
        
        with layout.row(True)(scale_x=0.5):
            text = ("3D" if cable_settings.is_3d else "2D")
            layout.prop(cable_settings, "is_3d", text=text, toggle=True)
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        
        cable_settings = context.object.cable_settings
        obj, curve = cable_settings.get_obj_curve()
        spline = curve.splines[0]
        
        with layout.row():
            layout.operator("object.select_whole_subheirarchy", text="Select whole")
            layout.operator("object.cable_unselect_children", text="Unselect")
            layout.operator("object.cable_to_mesh", text="To mesh")
        
        with layout.split(0.15):
            layout.label(text="Subdivs:")
            with layout.split(0.5):
                with layout.row(True):
                    icon = ('RESTRICT_VIEW_ON' if cable_settings.is_wireframe else 'RESTRICT_VIEW_OFF')
                    layout.prop(cable_settings, "is_wireframe", icon=icon, text="", toggle=True)
                    layout.prop(curve, "resolution_u", text="Preview")
                with layout.row(True):
                    layout.prop(obj, "hide_render", icon='RESTRICT_RENDER_OFF', text="", toggle=True)
                    layout.prop(curve, "render_resolution_u", text="Render")
        
        with layout.split(0.15):
            layout.label(text="Deform:")
            with layout.split(0.5):
                with layout.row(True):
                    layout.prop(spline, "radius_interpolation", text="")
                    layout.prop(curve, "use_radius", text="Radius", toggle=True)
                with layout.row(True):
                    layout.prop(curve, "use_stretch", text="Stretch", toggle=True)
                    layout.prop(curve, "use_deform_bounds", text="Clamp", toggle=True)
        
        with layout.split(0.15)(active=cable_settings.is_3d):
            layout.label(text="Twist:")
            with layout.split(0.5):
                with layout.row(True):
                    layout.prop(spline, "tilt_interpolation", text="")
                    layout.prop(curve, "twist_mode", text="")
                with layout.row(True):
                    layout.prop(curve, "twist_smooth", text="Smooth", slider=True)
                    layout.prop(cable_settings, "average_tilt", text="Average")
                    layout.operator("object.cable_auto_twist", text="", icon='FORCE_MAGNETIC') # FORCE_MAGNETIC RNA MOD_SCREW
        
        with layout.row():
            with layout.column(True):
                with layout.split(0.4, True):
                    layout.operator("object.cable_reset_profile_settings", text="Profile:")
                    with layout.row(True):
                        layout.prop(curve, "bevel_object", text="")
                        with layout.row(True)(active=bool(curve.bevel_object)):
                            icon = ('RADIOBUT_ON' if curve.use_fill_caps else 'RADIOBUT_OFF')
                            layout.prop(curve, "use_fill_caps", icon=icon, text="", toggle=True)
                
                with layout.column(True):
                    layout.prop(cable_settings, "extrude", text="Extrude")
                    layout.prop(cable_settings, "bevel_depth", text="Radius")
                    layout.prop(curve, "bevel_resolution", text="Resolution")
                    with layout.row(True):
                        layout.prop(curve, "fill_mode", text="")
                        layout.prop(curve, "use_fill_deform", text="", icon='SHAPEKEY_DATA', toggle=True)
            
            with layout.column(True):
                with layout.split(0.4, True):
                    layout.operator("object.cable_reset_tweaks_settings", text="Tweaks:")
                    with layout.row(True):
                        layout.prop(curve, "taper_object", text="")
                        with layout.row(True)(active=bool(curve.taper_object)):
                            icon = ('RADIOBUT_ON' if curve.use_map_taper else 'RADIOBUT_OFF')
                            layout.prop(curve, "use_map_taper", icon=icon, text="", toggle=True)
                
                with layout.column(True):
                    layout.prop(cable_settings, "thickness")
                    layout.prop(cable_settings, "offset", slider=True)
                    layout.prop(cable_settings, "split_angle")
                    
                    bevel_factor_mapping_icons = {'RESOLUTION':'PARTICLE_POINT', 'SEGMENTS':'PARTICLE_TIP', 'SPLINE':'PARTICLE_PATH'}
                    with layout.row(True):
                        if bevel_factor_mapping_exists:
                            icon = bevel_factor_mapping_icons[curve.bevel_factor_mapping_start]
                            layout.prop_menu_enum(curve, "bevel_factor_mapping_start", text="", icon=icon)
                        layout.prop(curve, "bevel_factor_start", text="", slider=True)
                        layout.prop(curve, "bevel_factor_end", text="", slider=True)
                        if bevel_factor_mapping_exists:
                            icon = bevel_factor_mapping_icons[curve.bevel_factor_mapping_end]
                            layout.prop_menu_enum(curve, "bevel_factor_mapping_end", text="", icon=icon)
        
        with layout.column(True):
            with layout.row(True):
                layout.prop(cable_settings, "wire_count", text="Wires")
                layout.prop(cable_settings, "wire_type", text="")
                with layout.row(True)(active=cable_settings.wire_is_braided):
                    layout.prop(cable_settings, "wire_twisting", text="Twisting")
                    layout.prop(cable_settings, "wire_twisting_align", text="Align", toggle=True)
                icon = ('RESTRICT_SELECT_ON' if cable_settings.wire_hide_select else 'RESTRICT_SELECT_OFF')
                layout.prop(cable_settings, "wire_hide_select", text="", icon=icon)
                icon = ('RESTRICT_VIEW_ON' if cable_settings.wire_hide else 'RESTRICT_VIEW_OFF')
                layout.prop(cable_settings, "wire_hide", text="", icon=icon)
                icon = ('RESTRICT_RENDER_ON' if cable_settings.wire_hide_render else 'RESTRICT_RENDER_OFF')
                layout.prop(cable_settings, "wire_hide_render", text="", icon=icon)
            with layout.row(True):
                layout.prop(cable_settings, "wire_scale", text="Scale")
                layout.prop(cable_settings, "wire_offset", text="Offset")
                layout.prop(cable_settings, "wire_step", text="Step")
                layout.prop(cable_settings, "wire_resolution", text="Sides")
            
            wire_material_slots = cable_settings.get_wire_material_slots()
            if not wire_material_slots:
                with layout.row(True)(enabled=False):
                    layout.prop(cable_settings, "no_wire_materials", toggle=True)
            else:
                with layout.row(True):
                    for i, material_slot in enumerate(wire_material_slots):
                        if i >= cable_settings.wire_count: break
                        layout.prop(material_slot, "material", text="", icon_only=True)
        
        with layout.box():
            with layout.row(True):
                layout.label(text="Attachments:")
                layout.operator("object.cable_attachment_add", text="Add")
            
            with layout.column():
                for i, attachment_obj in enumerate(cable_settings.attachment_iter()):
                    attachment_settings = attachment_obj.cable_settings
                    with layout.column(True):
                        with layout.row(True):
                            layout.operator("object.cable_attachment_delete", text="", icon='X').index = i
                            layout.prop(attachment_obj, "name", text="")
                            icon = {'MESH':'OUTLINER_OB_MESH', 'OBJECT':'OBJECT_DATA', 'GROUP':'GROUP'}[attachment_settings.attachment_template_type]
                            layout.prop_menu_enum(attachment_settings, "attachment_template_type", text="", icon=icon)
                            data_prop = attachment_settings.attachment_template_data_prop
                            layout.prop(data_prop[0], data_prop[1], text="")
                            layout.prop(attachment_obj, "hide_select", text="")
                            layout.prop(attachment_obj, "hide", text="")
                            layout.prop(attachment_obj, "hide_render", text="")
                        
                        with layout.row(True):
                            with layout.row(True)(active=attachment_settings.attachment_modifiers_possible):
                                layout.prop(attachment_settings, "attachment_deform", text="", icon='MOD_CURVE', toggle=True)
                            layout.prop(attachment_settings, "attachment_pos_absolute", text="POSITION")
                            layout.prop(attachment_settings, "attachment_pos_relative", text="position")
                            layout.prop(attachment_settings, "attachment_angle", text="Angle")
                            layout.prop(attachment_settings, "attachment_scale", text="Scale")
                            with layout.row(True)(scale_x=0.25):
                                layout.prop(attachment_settings, "attachment_forward_axis", text="")
                        
                        with layout.row(True)(active=attachment_settings.attachment_modifiers_possible):
                            layout.prop(attachment_settings, "attachment_array_use_length", text="", icon='CURVE_PATH')
                            if attachment_settings.attachment_array_use_length:
                                layout.prop(attachment_settings, "attachment_array_length_const", text="LENGTH")
                                layout.prop(attachment_settings, "attachment_array_length_factor", text="length")
                            else:
                                layout.prop(attachment_settings, "attachment_array_count", text="Count")
                            layout.prop(attachment_settings, "attachment_array_offset_abs", text="OFFSET")
                            layout.prop(attachment_settings, "attachment_array_offset_rel", text="offset")
                        
                        with layout.row(True)(enabled=attachment_settings.can_edit_materials):
                            for material_slot in attachment_obj.material_slots:
                                layout.prop(material_slot, "material", text="", icon_only=True)

# NOTE: the combination (curve.use_stretch = True, curve.use_deform_bounds = False) results in "glitchy" deformation

@addon.PropertyGroup
class CableSettingsPG:
    tag = "" | prop()
    
    tags_visible = {"WIRES", "WIRES_CAP0", "WIRES_CAP1", "ATTACHMENT"}
    
    def get_obj_curve(self):
        obj = self.id_data
        return (obj, (obj.data if obj.type == 'CURVE' else None))
    
    def get_spline(self):
        obj = self.id_data
        if obj.type != 'CURVE': return None
        curve = obj.data
        return (curve.splines[0] if curve and curve.splines else None)
    
    def collect_cable_objects(self, include_self=False, tags=None):
        obj = self.id_data
        if obj.type != 'CURVE': return None
        
        encapsulator = self._get_child(obj, "CABLE_EXTRAS")
        if not encapsulator: return None
        
        cable_objects = ([obj] if include_self else [])
        
        def walk_children(parent):
            if (not tags) or (parent.cable_settings.tag in tags):
                cable_objects.append(parent)
            for child in parent.children:
                walk_children(child)
        
        walk_children(encapsulator)
        
        return cable_objects
    
    def propagate_layers_to_children(self):
        obj = self.id_data
        if obj.type != 'CURVE': return
        
        encapsulator = self._get_child(obj, "CABLE_EXTRAS")
        if not encapsulator: return
        
        scene = bpy.context.scene
        object_bases = (scene.object_bases if scene else None)
        
        v3ds = []
        for sv3d in SmartView3D.find_in_ui(bpy.context.window):
            v3d = sv3d.space_data # layers_local_view are here
            lv3d = v3d.local_view # here layers_local_view are always False
            if not lv3d: continue
            if not BlUtil.Object.layers_intersect(v3d, obj, "layers_local_view"): continue
            v3ds.append(v3d)
        
        def walk_children(parent, layers, layers_local_view):
            if tuple(parent.layers) != layers:
                parent.layers = layers
            
            if object_bases and (tuple(parent.layers_local_view) != layers_local_view):
                base = object_bases.get(parent.name)
                if base:
                    for v3d in v3ds:
                        base.layers_from_view(v3d)
            
            for child in parent.children:
                walk_children(child, layers, layers_local_view)
        
        walk_children(encapsulator, tuple(obj.layers), tuple(obj.layers_local_view))
    
    def _get_modifier(self, obj, md_type, create=False, name=None):
        for modifier in obj.modifiers:
            if modifier.type == md_type:
                if (not name) or (modifier.name == name): return modifier
        if not create: return None
        return obj.modifiers.new(name or md_type.capitalize(), md_type)
    
    def _get_constraint(self, obj, cn_type, create=False, name=None):
        for constraint in obj.constraints:
            if constraint.type == cn_type:
                if (not name) or (constraint.name == name): return constraint
        if not create: return None
        constraint = obj.constraints.new(cn_type)
        constraint.name = name or cn_type.capitalize()
        return constraint
    
    def _get_degenerate_mesh(self, non_empty=True, name=None):
        if not name: name = ("DEGENERATE_MESH_NON_EMPTY" if non_empty else "DEGENERATE_MESH_EMPTY")
        mesh = bpy.data.meshes.get(name)
        if not mesh: mesh = bpy.data.meshes.new(name)
        if non_empty:
            rebuild = (len(mesh.vertices) != 3)
            if not rebuild:
                rebuild |= any(mesh.vertices[0].co)
                rebuild |= any(mesh.vertices[1].co)
                rebuild |= any(mesh.vertices[2].co)
            if rebuild:
                bm = bmesh.new()
                v0 = bm.verts.new(Vector())
                v1 = bm.verts.new(Vector())
                v2 = bm.verts.new(Vector())
                bm.faces.new([v0, v1, v2])
                bm.to_mesh(mesh)
                bm.free()
        else:
            if mesh.vertices:
                bm = bmesh.new()
                bm.to_mesh(mesh)
                bm.free()
        if not mesh.materials: mesh.materials.append(None)
        return mesh
    
    def _get_unit_bbox_mesh(self):
        name = "DEGENERATE_MESH_UNIT_BBOX"
        mesh = bpy.data.meshes.get(name)
        if not mesh: mesh = bpy.data.meshes.new(name)
        p0 = Vector((1,0,0))
        p1 = Vector((0,1,0))
        p2 = Vector((0,0,1))
        rebuild = (len(mesh.vertices) != 3)
        if not rebuild:
            rebuild |= (mesh.vertices[0].co != p0)
            rebuild |= (mesh.vertices[1].co != p1)
            rebuild |= (mesh.vertices[2].co != p2)
        if rebuild:
            bm = bmesh.new()
            v0 = bm.verts.new(p0)
            v1 = bm.verts.new(p1)
            v2 = bm.verts.new(p2)
            bm.to_mesh(mesh)
            bm.free()
        return mesh
    
    # Direct parenting is needed to keep things encapsulated.
    # ATTENTION: when parenting to curve, BLENDER ALWAYS MOVES
    # CURVE'S CHILDREN WITH THE FIRST POINT OF FIRST SPLINE.
    # ChildOf constraint is overriden by direct parenting,
    # so we have to use CopyLocation/CopyTransforms constraint
    # (which seems to override direct parent).
    def _get_child(self, obj, tag, create=False, data=None, visible=True, constraint=None):
        for child in obj.children:
            if child.cable_settings.tag == tag: return child
        if not create: return None
        init = (create if not isinstance(create, bool) else None)
        return self._add_child(obj, tag, init, data, visible, constraint)
    
    def _add_child(self, obj, tag, init=None, data=None, visible=True, constraint=None):
        if isinstance(data, str):
            if data == 'MESH':
                data = bpy.data.meshes.new(tag)
            elif data == 'MESH:0':
                data = self._get_degenerate_mesh(False)
            elif data == 'MESH:1':
                data = self._get_degenerate_mesh(True)
            elif data == 'MESH:BBOX':
                data = self._get_unit_bbox_mesh()
            elif data == 'MESH:CHOOSE':
                data = self._get_degenerate_mesh(True, "<Select a mesh>")
        child = bpy.data.objects.new(tag, data)
        bpy.context.scene.objects.link(child)
        
        child.cable_settings.tag = tag
        
        child.hide = (not visible)
        #child.hide_select = (not visible)
        child.hide_select = True # not selectable by default
        child.hide_render = (not visible)
        
        child.parent = obj
        if constraint: # COPY_TRANSFORMS or COPY_LOCATION
            constraint = self._get_constraint(child, constraint, True)
            constraint.target = obj
        
        if init: init(child)
        
        bpy.context.scene.update()
        
        return child
    
    def _iter_children(self, obj, tag):
        for child in obj.children:
            if child.cable_settings.tag == tag: yield child
    
    def _delete_child(self, child):
        try:
            bpy.context.scene.objects.unlink(child)
            bpy.data.objects.remove(child)
        except Exception:
            pass
    
    def _cable_child_get(self, tag, create=False, data=None, visible=True, constraint=None):
        obj = self.id_data
        encapsulator = self._get_child(obj, "CABLE_EXTRAS", create=bool(create), data='MESH:BBOX', visible=False, constraint='COPY_TRANSFORMS')
        if not encapsulator: return None
        return self._get_child(encapsulator, tag, create=create, data=data, visible=visible, constraint=constraint)
    
    def _cable_child_add(self, tag, init=None, data=None, visible=True, constraint=None):
        obj = self.id_data
        encapsulator = self._get_child(obj, "CABLE_EXTRAS", create=True, data='MESH:BBOX', visible=False, constraint='COPY_TRANSFORMS')
        if not encapsulator: return None
        return self._add_child(encapsulator, tag, init=init, data=data, visible=visible, constraint=constraint)
    
    def _cable_child_iter(self, tag):
        obj = self.id_data
        encapsulator = self._get_child(obj, "CABLE_EXTRAS")
        if not encapsulator: return
        for child in self._iter_children(encapsulator, tag):
            yield child
    
    def _cable_child_delete(self, child):
        if not child: return
        self._delete_child(child)
    
    def _cable_child_set_visibility(self, child, visible):
        if not child: return
        child.hide = (not visible)
        #child.hide_select = (not visible)
        #child.hide_select = True
        child.hide_render = (not visible)
    
    def _get_driver_fcurve(self, obj, data_path, index=-1, create=False):
        if obj.animation_data:
            for fcurve in obj.animation_data.drivers:
                if (fcurve.data_path == data_path) and (fcurve.array_index == index): return fcurve
        if not create: return None
        fcurve = obj.driver_add(data_path, index)
        if not isinstance(create, bool): create(fcurve) # expected callback function
        return fcurve
    
    def _enable_driver_fcurve(self, obj, data_path, index, enable):
        fcurve = self._get_driver_fcurve(obj, data_path, index)
        if not fcurve: return
        fcurve.mute = not enable
    
    def _init_driver_single_prop(self, fcurve, id_obj=None, data_path="", driver_type=None, expression="", var_name="var"):
        if not driver_type: driver_type = ('SCRIPTED' if expression else 'AVERAGE')
        
        driver = fcurve.driver
        driver.type = driver_type # MIN MAX SCRIPTED SUM AVERAGE
        driver.expression = expression
        
        var = (driver.variables[0] if driver.variables else driver.variables.new())
        var.name = var_name
        var.type = 'SINGLE_PROP' # LOC_DIFF ROTATION_DIFF TRANSFORMS SINGLE_PROP
        
        # 2 targets for LOC_DIFF, ROTATION_DIFF; 1 for TRANSFORMS, SINGLE_PROP
        target = var.targets[0]
        target.id_type = 'OBJECT'
        target.id = id_obj
        target.data_path = data_path
        
        if (len(fcurve.modifiers) > 1) or (fcurve.modifiers[0].type != 'GENERATOR'):
            while fcurve.modifiers:
                fcurve.modifiers.remove(fcurve.modifiers[0])
        
        fmod = (fcurve.modifiers[0] if len(fcurve.modifiers) else fcurve.modifiers.new(type='GENERATOR'))
        fmod.mode = 'POLYNOMIAL' # 'POLYNOMIAL', 'POLYNOMIAL_FACTORISED'
        fmod.use_additive = False
        fmod.poly_order = 1
        fmod.coefficients = [0.0, 1.0] # just some sane default
        fmod.use_restricted_range = False
        fmod.use_influence = False
        
        if hasattr(fcurve, "update"): fcurve.update() # absent in 2.70
    
    def _update_driver_single_prop(self, fcurve, coefficients=None, var_id=0, **kwargs):
        driver = fcurve.driver
        
        if var_id >= len(driver.variables):
            var = driver.variables[0]
            target = var.targets[0]
            id_obj = target.id
            data_path = target.data_path
            while var_id >= len(driver.variables):
                var = driver.variables.new()
                var.type = 'SINGLE_PROP'
                target = var.targets[0]
                target.id_type = 'OBJECT'
                target.id = id_obj
                target.data_path = data_path
        
        var = driver.variables[var_id]
        target = var.targets[0]
        
        for k, v in kwargs.items():
            if k == "expression":
                driver.type = 'SCRIPTED'
                driver.expression = v
            elif k == "driver_type":
                driver.type = v
            elif k == "var_name":
                var.name = v
            elif k == "id_obj":
                target.id = v
            elif k == "data_path":
                target.data_path = v
        
        if coefficients:
            fmod = fcurve.modifiers[0] # expected to be 'GENERATOR'
            fmod.mode = 'POLYNOMIAL'
            fmod.poly_order = len(coefficients) - 1
            fmod.coefficients = coefficients
        
        if hasattr(fcurve, "update"): fcurve.update() # absent in 2.70
    
    def _get_main_cable_settings(self):
        obj = self.id_data
        encapsulator = obj.parent
        if encapsulator and (encapsulator.cable_settings.tag == "CABLE_EXTRAS"):
            main_obj = encapsulator.parent
            if main_obj and main_obj.cable_settings.get_spline():
                self = main_obj.cable_settings
        return self
    
    # Length-calculation methods and properties
    def _length_calculator_init(self, length_calc):
        obj = self.id_data
        #encapsulator = length_calc.parent
        md_array = self._get_modifier(length_calc, 'ARRAY', True)
        md_array.fit_type = 'FIT_CURVE'
        md_array.curve = obj
        md_array.use_constant_offset = True
        # Even if source mesh is empty, Blender doesn't skip
        # the array calculations, so we can't use arbitrary precision
        # 0.0025 is not too slow on my computer for 400-meter curve
        md_array.constant_offset_displace = Vector((0, 0, 0.0025))
        md_array.use_relative_offset = False
        md_array.use_object_offset = False
        md_array.use_merge_vertices = False
        #md_array.start_cap = encapsulator
        #md_array.end_cap = encapsulator
        length_calc.scale = Vector((0,0,0))
    
    # This method is called (indirectly) from attachments too
    # Used by calculate_length, _init_length_driver
    def _length_calculator_get(self, create=False):
        self = self._get_main_cable_settings()
        if create: create = self._length_calculator_init
        # We cannot use absolutely empty mesh, because in this case
        # Blender will print warnings in the console on each object update
        return self._cable_child_get("LENGTH_CALC", create=create, data='MESH:1', visible=False)
    
    length_calc_prop = "bound_box[1][2]"
    length_calc_value = (lambda self, length_calc: length_calc.bound_box[1][2])
    
    def calculate_length(self, create=False):
        obj, curve = self.get_obj_curve()
        if not curve: return 0.0
        encapsulator = self._get_child(obj, "CABLE_EXTRAS")
        delete_afterwards = (not encapsulator) and (not create)
        length_calc = self._length_calculator_get(True)
        value = self.length_calc_value(length_calc)
        if delete_afterwards:
            self._cable_child_delete(length_calc)
            self._cable_child_delete(encapsulator)
        return value
    
    def _init_length_driver(self, fcurve):
        id_obj = self._length_calculator_get(True)
        data_path = self.length_calc_prop
        self._init_driver_single_prop(fcurve, id_obj, data_path)
    
    def _set_length_driver(self, obj, data_path, index, coefficients, inverse=False):
        fcurve = self._get_driver_fcurve(obj, data_path, index, create=self._init_length_driver)
        self._update_driver_single_prop(fcurve, coefficients, data_path=self.length_calc_prop,
            expression=("1.0/max({}, 1e-6)" if inverse else "{}").format("var"), var_name="var")
    
    def _init_scale_driver(self, fcurve):
        main_self = self._get_main_cable_settings()
        encapsulator = main_self._get_child(main_self.id_data, "CABLE_EXTRAS")
        self._init_driver_single_prop(fcurve, encapsulator, "dimensions.x", expression="x")
    
    def _set_scale_driver(self, obj, data_path, index, axis, coefficients, inverse=False):
        fcurve = self._get_driver_fcurve(obj, data_path, index, create=self._init_scale_driver)
        if axis == "magnitude":
            magnitude_expr = "sqrt(x*x + y*y + z*z)"
            self._update_driver_single_prop(fcurve, data_path="dimensions.x", var_name="x", var_id=0)
            self._update_driver_single_prop(fcurve, data_path="dimensions.y", var_name="y", var_id=1)
            self._update_driver_single_prop(fcurve, data_path="dimensions.z", var_name="z", var_id=2)
            self._update_driver_single_prop(fcurve, coefficients, expression=("1.0/max({}, 1e-6)" if inverse else "{}").format(magnitude_expr))
        else:
            self._update_driver_single_prop(fcurve, coefficients, data_path="dimensions."+axis,
                expression=("1.0/{}" if inverse else "{}").format(axis), var_name=axis)
    
    def _init_length_scale_driver(self, fcurve):
        main_self = self._get_main_cable_settings()
        encapsulator = main_self._get_child(main_self.id_data, "CABLE_EXTRAS")
        length_calc = main_self._length_calculator_get(True)
        
        self._init_driver_single_prop(fcurve)
        self._update_driver_single_prop(fcurve, var_id=0, var_name="L", id_obj=length_calc, data_path=self.length_calc_prop)
        self._update_driver_single_prop(fcurve, var_id=1, var_name="SX", id_obj=encapsulator, data_path="dimensions.x")
        self._update_driver_single_prop(fcurve, var_id=2, var_name="SY", id_obj=encapsulator, data_path="dimensions.y")
        self._update_driver_single_prop(fcurve, var_id=3, var_name="SZ", id_obj=encapsulator, data_path="dimensions.z")
    
    def _set_length_scale_driver(self, obj, data_path, index, expresion, coefficients):
        fcurve = self._get_driver_fcurve(obj, data_path, index, create=self._init_length_scale_driver)
        self._update_driver_single_prop(fcurve, coefficients, expression=expresion)
    
    # Object-based properties
    def _get(self):
        obj, curve = self.get_obj_curve()
        if not curve: return False
        return (obj.draw_type in ('WIRE', 'BOUNDS'))
    def _set(self, value):
        obj, curve = self.get_obj_curve()
        if not curve: return
        obj.draw_type = ('WIRE' if value else 'TEXTURED')
    is_wireframe = False | prop("Toggle textured/wireframe display", "Is wireframe", get=_get, set=_set)
    
    # Curve-based properties
    def _get(self):
        obj, curve = self.get_obj_curve()
        if not curve: return False
        fill_mode = ('FULL' if curve.dimensions == '3D' else 'NONE')
        if curve.fill_mode != fill_mode: return False
        if curve.offset != 0.0: return False
        if curve.use_stretch: return False
        if curve.use_deform_bounds: return False
        return True
    def _set(self, value):
        obj, curve = self.get_obj_curve()
        if not curve: return
        if value:
            fill_mode = ('FULL' if curve.dimensions == '3D' else 'NONE')
            curve.fill_mode = fill_mode
            curve.offset = 0.0
            curve.use_stretch = False
            curve.use_deform_bounds = False
    is_cable = True | prop("Cable sanity check", "Is cable", get=_get, set=_set)
    
    def _get(self):
        obj, curve = self.get_obj_curve()
        if not curve: return True
        return (curve.dimensions == '3D')
    def _set(self, value):
        obj, curve = self.get_obj_curve()
        if not curve: return
        curve.dimensions = ('3D' if value else '2D')
    is_3d = True | prop("Is 3D", "3D", get=_get, set=_set)
    
    def _get(self):
        obj, curve = self.get_obj_curve()
        if not curve: return True
        return curve.extrude
    def _set(self, value):
        obj, curve = self.get_obj_curve()
        if not curve: return
        curve.extrude = value
        self.on_wire_changed(bpy.context)
    extrude = 0.0 | prop("Curve extrusion (also influences \"bus\" wires)", "Extrude", min=0.0, step=0.1, precision=3, get=_get, set=_set)
    
    def _get(self):
        obj, curve = self.get_obj_curve()
        if not curve: return True
        return curve.bevel_depth
    def _set(self, value):
        obj, curve = self.get_obj_curve()
        if not curve: return
        curve.bevel_depth = value
        self.on_wire_changed(bpy.context)
    bevel_depth = 0.0 | prop("Bevel radius (also influences \"braided\" wires)", "Radius", min=0.0, step=0.1, precision=3, get=_get, set=_set)
    
    # Spline-based properties
    def _get(self):
        spline = self.get_spline()
        if not spline: return 0.0
        points = (spline.bezier_points if spline.type == 'BEZIER' else spline.points)
        if not points: return 0.0
        return sum(point.tilt for point in points) / len(points)
    def _set(self, value):
        spline = self.get_spline()
        if not spline: return
        points = (spline.bezier_points if spline.type == 'BEZIER' else spline.points)
        if not points: return
        delta = value - (sum(point.tilt for point in points) / len(points))
        for point in points:
            point.tilt += delta
    average_tilt = 0.0 | prop("Average tilt", "Average tilt", get=_get, set=_set, subtype='ANGLE', unit='ROTATION')
    
    # Modifier-based properties (Solidify)
    def _get_curve_modifier(self, kind, create=False):
        obj = self.id_data
        if obj.type != 'CURVE': return None
        # these modifiers are not orthogonal
        return dict(
            solidify = self._get_modifier(obj, 'SOLIDIFY', create),
            edge_split = self._get_modifier(obj, 'EDGE_SPLIT', create),
        ).get(kind)
    
    def _get(self):
        solidify = self._get_curve_modifier("solidify")
        if not solidify: return 0.0
        return -solidify.thickness
    def _set(self, value):
        value_non_default = (value != 0.0)
        solidify = self._get_curve_modifier("solidify", value_non_default)
        if not solidify: return
        solidify.show_viewport = value_non_default
        solidify.show_render = value_non_default
        solidify.thickness = -value
    thickness = 0.0 | prop("Thickness of the shell", "Thickness", get=_get, set=_set, step=0.1, precision=4)
    
    def _get(self):
        solidify = self._get_curve_modifier("solidify")
        if not solidify: return -1.0
        return solidify.offset
    def _set(self, value):
        solidify = self._get_curve_modifier("solidify", True)
        if not solidify: return
        solidify.offset = value
    offset = -1.0 | prop("Offset the thickness from the center", "Offset", get=_get, set=_set, min=-1.0, max=1.0, step=1, precision=4)
    
    def _get(self):
        solidify = self._get_curve_modifier("solidify")
        if not solidify: return False
        return solidify.use_even_offset
    def _set(self, value):
        solidify = self._get_curve_modifier("solidify", True)
        if not solidify: return
        solidify.use_even_offset = value
    use_even_offset = False | prop("Maintain thickness by adjusting to sharp corners (slow)", "Even thickness", get=_get, set=_set)
    
    def _get(self):
        solidify = self._get_curve_modifier("solidify")
        if not solidify: return False
        return solidify.use_rim_only
    def _set(self, value):
        solidify = self._get_curve_modifier("solidify", True)
        if not solidify: return
        solidify.use_rim_only = value
    use_rim_only = False | prop("Only add the rim to the original data", "Only rim", get=_get, set=_set)
    
    # Modifier-based properties (Edge Split)
    def _get(self):
        edge_split = self._get_curve_modifier("edge_split")
        if not edge_split: return math.pi
        return edge_split.split_angle
    def _set(self, value):
        value_non_default = (abs(value - math.pi) > 1e-6)
        edge_split = self._get_curve_modifier("edge_split", value_non_default)
        if not edge_split: return
        edge_split.show_viewport = value_non_default
        edge_split.show_render = value_non_default
        edge_split.split_angle = value
        edge_split.use_edge_angle = value_non_default
        edge_split.use_edge_sharp = False # curve doesn't have sharp-marked edges anyway
    split_angle = math.pi | prop("Angle above which to split edges", "Split Angle", get=_get, set=_set, min=0.0, max=math.pi, subtype='ANGLE', unit='ROTATION')
    
    # Wire-related methods & properties
    def wire_update(self):
        obj, curve = self.get_obj_curve()
        if not curve: return
        
        extrude_bevel = abs(curve.extrude) + abs(curve.bevel_depth)
        wire_possible = (self.wire_count > 0) and (self.wire_step > 0) and (extrude_bevel > 0)
        if not wire_possible:
            wire_obj = self._cable_child_get("WIRES")
            if wire_obj: # don't delete object/mesh, because it stores wire materials
                mesh = wire_obj.data
                bm = bmesh.new()
                bm.to_mesh(mesh) # clear mesh
                bm.free()
                self._cable_child_set_visibility(wire_obj, False)
                wire_cap0_obj = self._get_child(wire_obj, "WIRES_CAP0", False)
                self._cable_child_set_visibility(wire_cap0_obj, False)
                wire_cap1_obj = self._get_child(wire_obj, "WIRES_CAP1", False)
                self._cable_child_set_visibility(wire_cap1_obj, False)
            return
        
        wire_obj = self._cable_child_get("WIRES", create=True, data='MESH')
        if not wire_obj: return
        self._cable_child_set_visibility(wire_obj, True)
        
        wire_type = ('BRAIDED' if self.wire_is_braided else 'BUS')
        
        n = self.wire_count
        
        if wire_type == 'BUS':
            wire_twisting = 0.0
            bus_halfwidth = curve.extrude + curve.bevel_depth
            wire_base_radius = bus_halfwidth / n
        elif wire_type == 'BRAIDED':
            wire_twisting = self.wire_twisting
            outer_radius = curve.bevel_depth
            if n == 1:
                wire_base_radius = outer_radius
                base_offset = 0.0
                angle_offset = 0.0
            elif n == 2:
                wire_base_radius = outer_radius / 2
                base_offset = outer_radius / 2
                angle_offset = math.pi
            else: # incircle of an isosceles triangle
                # http://mathworld.wolfram.com/Inradius.html
                angle_offset = (math.pi*2) / n
                if outer_radius > 0:
                    h = outer_radius
                    a = 2 * h * math.tan(angle_offset / 2)
                    r = (math.sqrt(a*a + 4*h*h) - a) * (a / (4*h))
                    wire_base_radius = r
                else:
                    wire_base_radius = 0.0
                base_offset = outer_radius - wire_base_radius
        
        mesh = wire_obj.data
        
        materials = mesh.materials
        materials_delta = n - len(materials)
        if materials_delta > 0:
            last_material = (materials[-1] if len(materials) > 0 else None)
            for i in range(materials_delta):
                materials.append(last_material)
        elif materials_delta < 0:
            pass # deleting material slots is probably undesirable
            #for i in range(abs(materials_delta)):
            #    materials.pop(-1, False)
        
        # Note: even bm_cap = bm.copy() seems to cause crashes when bm_cap.to_mesh(cap_mesh) is used
        bm = bmesh.new()
        bm_cap = bmesh.new() # completely independent to avoid crashes
        
        if wire_type == 'BUS':
            wire_radius = wire_base_radius * self.wire_scale * 0.995
            
            w_step = (bus_halfwidth*2) / n
            
            for i in range(n):
                matrix = Matrix.Translation(Vector((self.wire_offset, (i+0.5)*w_step - bus_halfwidth, 0)))
                bmesh.ops.create_circle(bm, cap_ends=True, cap_tris=False, segments=self.wire_resolution, diameter=wire_radius, matrix=matrix)
                bmesh.ops.create_circle(bm_cap, cap_ends=True, cap_tris=False, segments=self.wire_resolution, diameter=wire_radius, matrix=matrix)
        elif wire_type == 'BRAIDED':
            # 1st iteration: find approximate radius
            # 2nd interation: adjust offset so that wire sticks to the outer radius
            for i in range(2):
                r_offset = base_offset + self.wire_offset
                
                twist_direction_angle = -math.atan(wire_twisting * r_offset)
                if not self.wire_twisting_align: twist_direction_angle = 0.0
                
                matrix0 = Matrix.Rotation(twist_direction_angle, 4, Vector((0, 1, 0)))
                matrix0 = Matrix.Translation(Vector((0, r_offset, 0))) * matrix0
                
                if (abs(twist_direction_angle) > 0) and (abs(wire_twisting) > 1e-6):
                    one_cycle_offset = (2 * math.pi) / wire_twisting
                    one_wire_offset = one_cycle_offset / n
                    
                    delta_arc = math.cos(abs(twist_direction_angle)) * one_wire_offset
                    delta_arc_L = math.cos(abs(twist_direction_angle)) * delta_arc
                    delta_arc_R = math.sin(abs(twist_direction_angle)) * delta_arc
                    delta_arc_W = delta_arc_R / r_offset # angle
                    
                    vA0 = Vector(matrix0.translation)
                    vA1 = Matrix.Rotation(delta_arc_W, 4, Vector((0, 0, 1))) * vA0
                    vA1.z = one_wire_offset - delta_arc_L
                    
                    wire_radius = min(wire_base_radius, (vA1 - vA0).magnitude * 0.5)
                    base_offset = outer_radius - wire_radius
                else:
                    wire_radius = wire_base_radius
            
            wire_radius = wire_radius * self.wire_scale * 0.995
            
            for i in range(n):
                matrix = Matrix.Rotation(i*angle_offset, 4, Vector((0, 0, 1))) * matrix0
                bmesh.ops.create_circle(bm, cap_ends=True, cap_tris=False, segments=self.wire_resolution, diameter=wire_radius, matrix=matrix)
                bmesh.ops.create_circle(bm_cap, cap_ends=True, cap_tris=False, segments=self.wire_resolution, diameter=wire_radius, matrix=matrix)
        
        for id, face in enumerate(bm.faces):
            face.smooth = True
            face.material_index = id
        
        for id, face in enumerate(bm_cap.faces):
            face.smooth = False
            face.material_index = id
        
        bm.to_mesh(mesh)
        bm.free()
        
        # Note: compensation scale = (3 ^ 0.5) / ((scale.x^2 + scale.y^2 + scale.z^2) ^ 0.5)
        def drive_by_length_scale(target, data_path, index, expresion, coefficients):
            if isinstance(target, bpy.types.Modifier):
                data_path = "modifiers[\"{}\"].{}".format(target.name, data_path)
                target = wire_obj
            elif isinstance(target, bpy.types.Constraint):
                data_path = "constraints[\"{}\"].{}".format(target.name, data_path)
                target = wire_obj
            self._set_length_scale_driver(target, data_path, index, expresion, coefficients)
        
        md_screw = self._get_modifier(wire_obj, 'SCREW', True)
        drive_by_length_scale(md_screw, "angle", -1, "L * sqrt(3.0 / (SX*SX + SY*SY + SZ*SZ))", (0.0, wire_twisting))
        drive_by_length_scale(md_screw, "steps", -1, "L * sqrt(3.0 / (SX*SX + SY*SY + SZ*SZ))", (0.0, 1.0/self.wire_step))
        drive_by_length_scale(md_screw, "screw_offset", -1, "L * sqrt(3.0 / (SX*SX + SY*SY + SZ*SZ))", (0.0, 1.0))
        md_screw.axis = 'Z'
        md_screw.object = None
        md_screw.iterations = 1
        md_screw.use_object_screw_offset = False
        md_screw.render_steps = md_screw.steps
        md_screw.use_normal_calculate = False
        md_screw.use_normal_flip = True
        md_screw.use_smooth_shade = True
        md_screw.use_stretch_u = False
        md_screw.use_stretch_v = False
        
        md_curve = self._get_modifier(wire_obj, 'CURVE', True)
        md_curve.deform_axis = 'POS_Z'
        md_curve.object = obj
        
        # Wire caps
        wire_cap0_obj = self._get_child(wire_obj, "WIRES_CAP0", True, data='MESH')
        cap_mesh = wire_cap0_obj.data
        wire_cap1_obj = self._get_child(wire_obj, "WIRES_CAP1", True, data=cap_mesh)
        
        bm_cap.to_mesh(cap_mesh)
        bm_cap.free()
        
        while len(cap_mesh.materials) > len(mesh.materials):
            cap_mesh.materials.pop(-1, False)
        
        while len(cap_mesh.materials) < len(mesh.materials):
            cap_mesh.materials.append(None)
        
        for i, material in enumerate(mesh.materials):
            cap_mesh.materials[i] = material
        
        self._cable_child_set_visibility(wire_cap0_obj, True)
        wire_cap0_obj.data = cap_mesh
        wire_cap0_obj.location = Vector((0, 0, 0))
        wire_cap0_obj.rotation_euler = Euler((0, 0, 0))
        
        md_curve = self._get_modifier(wire_cap0_obj, 'CURVE', True)
        md_curve.deform_axis = 'POS_Z'
        md_curve.object = obj
        
        self._cable_child_set_visibility(wire_cap1_obj, True)
        wire_cap1_obj.data = cap_mesh
        drive_by_length_scale(wire_cap1_obj, "location", 2, "L * sqrt(3.0 / (SX*SX + SY*SY + SZ*SZ))", (0.0, 1.0))
        drive_by_length_scale(wire_cap1_obj, "rotation_euler", 2, "L * sqrt(3.0 / (SX*SX + SY*SY + SZ*SZ))", (0.0, wire_twisting))
        
        md_curve = self._get_modifier(wire_cap1_obj, 'CURVE', True)
        md_curve.deform_axis = 'POS_Z'
        md_curve.object = obj
    
    def wire_material_ids(self):
        material_ids = []
        wire_obj = self._cable_child_get("WIRES")
        if wire_obj:
            mesh = wire_obj.data
            for material in mesh.materials:
                material_ids.append(material.as_pointer() if material else 0)
        return material_ids
    
    def get_wire_material_slots(self):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return None
        return wire_obj.material_slots
    
    no_wire_materials = False | prop("No wire materials", "No wire materials", get=(lambda self: False)) # just for UI
    
    @property
    def wire_is_braided(self):
        if self.wire_type == 'AUTO':
            obj, curve = self.get_obj_curve()
            if not curve: return True
            return (curve.extrude == 0)
        return (self.wire_type == 'BRAIDED')
    
    def on_wire_changed(self, context):
        self.wire_update()
    
    wire_type = 'AUTO' | prop("Type of wire", "Wire type", update=on_wire_changed, items=[
        ('AUTO', "Auto", "Braided when curve extrusion is 0, Bus otherwise"),
        ('BUS', "Bus", "Flat cable"),
        ('BRAIDED', "Braided", "Braided cable"),
    ])
    wire_count = 0 | prop("Number of wires", "Wire count", min=0, update=on_wire_changed)
    wire_scale = 1.0 | prop("Wire scale", "Wire scale", min=0.0, step=0.1, precision=3, update=on_wire_changed)
    wire_resolution = 8 | prop("Wire profile resolution", "Wire resolution", min=3, max=32, update=on_wire_changed)
    wire_step = 0.1 | prop("Wire step", "Wire step", subtype='DISTANCE', unit='LENGTH', min=0.01, step=0.1, precision=3, update=on_wire_changed)
    wire_offset = 0.0 | prop("Wire offset", "Wire offset", subtype='DISTANCE', unit='LENGTH', step=0.1, precision=3, update=on_wire_changed)
    wire_twisting = 0.0 | prop("Wire twisting per unit length", "Wire twisting", subtype='ANGLE', unit='ROTATION', update=on_wire_changed)
    wire_twisting_align = True | prop("Align wire profile to twisting direction", "Wire align", update=on_wire_changed)
    
    def _get(self):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return False
        return wire_obj.hide
    def _set(self, value):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return
        wire_obj.hide = value
        wire_cap0_obj = self._get_child(wire_obj, "WIRES_CAP0")
        if wire_cap0_obj: wire_cap0_obj.hide = value
        wire_cap1_obj = self._get_child(wire_obj, "WIRES_CAP1")
        if wire_cap1_obj: wire_cap1_obj.hide = value
    wire_hide = False | prop("Hide in viewport", "Hide", get=_get, set=_set)
    
    def _get(self):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return False
        return wire_obj.hide_render
    def _set(self, value):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return
        wire_obj.hide_render = value
        wire_cap0_obj = self._get_child(wire_obj, "WIRES_CAP0")
        if wire_cap0_obj: wire_cap0_obj.hide_render = value
        wire_cap1_obj = self._get_child(wire_obj, "WIRES_CAP1")
        if wire_cap1_obj: wire_cap1_obj.hide_render = value
    wire_hide_render = False | prop("Hide during render", "Hide render", get=_get, set=_set)
    
    def _get(self):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return False
        return wire_obj.hide_select
    def _set(self, value):
        wire_obj = self._cable_child_get("WIRES")
        if not wire_obj: return
        wire_obj.hide_select = value
        wire_cap0_obj = self._get_child(wire_obj, "WIRES_CAP0")
        if wire_cap0_obj: wire_cap0_obj.hide_select = value
        wire_cap1_obj = self._get_child(wire_obj, "WIRES_CAP1")
        if wire_cap1_obj: wire_cap1_obj.hide_select = value
    wire_hide_select = False | prop("Forbid selecting", "Forbid selecting", get=_get, set=_set)
    
    # Attachment-related methods and properties (on the cable)
    def attachment_add(self):
        attachment_obj = self._cable_child_add("ATTACHMENT", data='MESH:CHOOSE')
        attachment_obj.cable_settings.attachment_update()
        return attachment_obj
    
    def attachment_delete(self, index):
        delete_all = (index == 'ALL') or (index == '*')
        children = tuple(self._cable_child_iter("ATTACHMENT"))
        for i, child in enumerate(children):
            if delete_all or (i == index): self._cable_child_delete(child)
    
    def attachment_iter(self):
        for child in self._cable_child_iter("ATTACHMENT"):
            yield child
    
    def attachment_template_ids(self):
        template_ids = []
        for attachment_obj in self.attachment_iter():
            attachment_settings = attachment_obj.cable_settings
            template_data, template_prop = attachment_settings.attachment_template_data_prop
            template = (getattr(template_data, template_prop) if template_data else None)
            template_ids.append(template.as_pointer() if template else 0)
        return template_ids
    
    def attachment_update_all(self):
        for attachment_obj in self.attachment_iter():
            attachment_settings = attachment_obj.cable_settings
            attachment_settings.attachment_update()
    
    # Attachment-related methods and properties (on the attachments themselves)
    def attachment_update(self):
        if self.tag != "ATTACHMENT": return
        attachment_obj = self.id_data
        
        encapsulator = attachment_obj.parent
        if not encapsulator: return
        if encapsulator.cable_settings.tag != "CABLE_EXTRAS": return
        
        obj = encapsulator.parent
        if not obj: return
        if obj.type != 'CURVE': return
        curve = obj.data
        
        def enable_modifier(md, enable):
            md.show_render = enable
            md.show_viewport = enable
        
        def enable_constraint(cn, enable):
            cn.mute = not enable
        
        def switch_axis_driver(data_obj, data_path, driver_axis, size=3):
            for i in range(size):
                self._enable_driver_fcurve(data_obj, data_path, i, (i == driver_axis))
        
        def drive_modifier_by_length(md, data_path, index, coefs, switch=True, inverse=False):
            data_obj = attachment_obj
            data_path = "modifiers[\"{}\"].{}".format(md.name, data_path)
            size = (switch if isinstance(switch, int) else 3)
            if switch and (index != -1): switch_axis_driver(data_obj, data_path, driver_axis, size=size)
            self._set_length_driver(data_obj, data_path, index, coefs, inverse=inverse)
        
        def drive_constraint_by_length(cn, data_path, index, coefs, switch=True, inverse=False):
            data_obj = attachment_obj
            data_path = "constraints[\"{}\"].{}".format(cn.name, data_path)
            size = (switch if isinstance(switch, int) else 3)
            if switch and (index != -1): switch_axis_driver(data_obj, data_path, driver_axis, size=size)
            self._set_length_driver(data_obj, data_path, index, coefs, inverse=inverse)
        
        driver_axis = self.driver_axis_map[self.attachment_forward_axis]
        axis_sign = self.sign_axis_map[self.attachment_forward_axis]
        axis_vector = self.vector_axis_map[self.attachment_forward_axis]
        
        # Initialize modifiers in the correct order
        md_cap = self._get_modifier(attachment_obj, 'ARRAY', True, name="Cap")
        md_array = self._get_modifier(attachment_obj, 'ARRAY', True, name="Array")
        md_curve = self._get_modifier(attachment_obj, 'CURVE', True, name="Curve")
        
        # Initialize constraints in the correct order
        cn_limit_loc = self._get_constraint(attachment_obj, 'LIMIT_LOCATION', True, name="LimitLoc")
        cn_limit_rot = self._get_constraint(attachment_obj, 'LIMIT_ROTATION', True, name="LimitRot")
        cn_follow_path = self._get_constraint(attachment_obj, 'FOLLOW_PATH', True, name="FollowPath")
        
        degenerate_mesh = self._get_degenerate_mesh(True, "<Select a mesh>")
        
        # Clear/initialize the corresponding settings
        if self.attachment_template_type != 'MESH':
            attachment_obj.data = degenerate_mesh
        else: # mesh is assigned by the user
            pass
        
        if self.attachment_template_type != 'OBJECT':
            enable_modifier(md_cap, False)
            #md_cap.start_cap = None
            #md_cap.end_cap = None
        else: # cap object is assigned by the user
            cap_obj = md_cap.start_cap
            if cap_obj and (cap_obj.type == 'MESH'):
                attachment_obj.data = cap_obj.data
                enable_modifier(md_cap, False)
            else:
                attachment_obj.data = degenerate_mesh
                enable_modifier(md_cap, True)
                md_cap.fit_type = 'FIXED_COUNT'
                md_cap.count = 1
                md_cap.use_constant_offset = False
                md_cap.use_relative_offset = False
                md_cap.use_object_offset = False
                md_cap.use_merge_vertices = False
        
        if self.attachment_template_type != 'GROUP':
            attachment_obj.dupli_type = 'NONE'
            #attachment_obj.dupli_group = None
        else: # group is assigned by the user
            attachment_obj.dupli_type = 'GROUP'
        
        slot_link = ('OBJECT' if attachment_obj.data == degenerate_mesh else 'DATA')
        for material_slot in attachment_obj.material_slots:
            material_slot.link = slot_link
        
        # Array modifier
        if self.attachment_array_use_length:
            use_array = ((self.attachment_array_length_const != 0) or (self.attachment_array_length_factor != 0))
        else:
            use_array = (self.attachment_array_count > 1)
        use_array &= ((self.attachment_array_offset_abs != 0) or (self.attachment_array_offset_rel != 0))
        use_array &= self.attachment_modifiers_possible
        
        enable_modifier(md_array, use_array)
        if use_array:
            md_array.curve = obj
            if self.attachment_array_use_length:
                md_array.fit_type = 'FIT_LENGTH'
                drive_modifier_by_length(md_array, "fit_length", -1, (self.attachment_array_length_const, self.attachment_array_length_factor))
            else:
                md_array.fit_type = 'FIXED_COUNT'
                md_array.count = self.attachment_array_count
            md_array.use_constant_offset = True
            md_array.constant_offset_displace = axis_vector * self.attachment_array_offset_abs
            md_array.use_relative_offset = True
            md_array.relative_offset_displace = axis_vector * self.attachment_array_offset_rel
            md_array.use_object_offset = False
            #md_array.offset_object = None
            md_array.use_merge_vertices = True # sometimes False can be useful?
            md_array.merge_threshold = 0.001
        
        attachment_obj.scale = Vector((1,1,1)) * self.attachment_scale
        
        # constraints override loc/rot/scale drivers, so there's no necessity to mute/unmute drivers
        use_deform = self.attachment_deform and self.attachment_modifiers_possible
        if use_deform:
            enable_modifier(md_curve, True)
            enable_constraint(cn_limit_loc, False)
            enable_constraint(cn_limit_rot, False)
            enable_constraint(cn_follow_path, False)
            
            md_curve.deform_axis = self.curve_deform_axis_map[self.attachment_forward_axis]
            md_curve.object = obj
            
            attachment_obj.location = Vector() # muting a driver doesn't revert the property values
            switch_axis_driver(attachment_obj, "location", driver_axis)
            self._set_length_driver(attachment_obj, "location", driver_axis, (axis_sign*self.attachment_pos_absolute, axis_sign*self.attachment_pos_relative))
            
            euler = Euler()
            euler[driver_axis] = self.attachment_angle
            attachment_obj.rotation_euler = euler
        else:
            enable_modifier(md_curve, False)
            enable_constraint(cn_limit_loc, True)
            enable_constraint(cn_limit_rot, True)
            enable_constraint(cn_follow_path, True)
            
            forward_axis = self.follow_path_axis_forward_map[self.attachment_forward_axis]
            up_axis, extra_angles = self.follow_path_axis_up_map[self.attachment_forward_axis]
            extra_angles = Vector(extra_angles) * (math.pi / 180.0)
            extra_angles[driver_axis] += self.attachment_angle
            
            cn_limit_loc.mute = False
            cn_limit_loc.use_min_x = True
            cn_limit_loc.min_x = 0.0
            cn_limit_loc.use_max_x = True
            cn_limit_loc.max_x = 0.0
            cn_limit_loc.use_min_y = True
            cn_limit_loc.min_y = 0.0
            cn_limit_loc.use_max_y = True
            cn_limit_loc.max_y = 0.0
            cn_limit_loc.use_min_z = True
            cn_limit_loc.min_z = 0.0
            cn_limit_loc.use_max_z = True
            cn_limit_loc.max_z = 0.0
            cn_limit_loc.use_transform_limit = False
            cn_limit_loc.owner_space = 'WORLD'
            cn_limit_loc.influence = 1.0
            
            cn_limit_rot.mute = False
            cn_limit_rot.use_limit_x = True
            cn_limit_rot.min_x = extra_angles[0]
            cn_limit_rot.max_x = extra_angles[0]
            cn_limit_rot.use_limit_y = True
            cn_limit_rot.min_y = extra_angles[1]
            cn_limit_rot.max_y = extra_angles[1]
            cn_limit_rot.use_limit_z = True
            cn_limit_rot.min_z = extra_angles[2]
            cn_limit_rot.max_z = extra_angles[2]
            cn_limit_rot.use_transform_limit = False
            cn_limit_rot.owner_space = 'WORLD'
            cn_limit_rot.influence = 1.0
            
            cn_follow_path.target = obj
            cn_follow_path.use_curve_follow = True
            cn_follow_path.use_curve_radius = True # maybe sometimes this is useful to be False
            #cn_follow_path.use_fixed_location = False # False: absolute; True: relative
            cn_follow_path.use_fixed_location = True # False: absolute; True: relative
            cn_follow_path.forward_axis = forward_axis
            cn_follow_path.up_axis = up_axis
            
            # We cannot do this because it will create a dependency cycle
            #self._set_length_driver(curve, "path_duration", -1, (0.0, 1.0))
            
            #drive_constraint_by_length(cn_follow_path, "offset", -1, (self.attachment_pos_absolute, self.attachment_pos_relative))
            drive_constraint_by_length(cn_follow_path, "offset_factor", -1, (self.attachment_pos_relative, self.attachment_pos_absolute), inverse=True)
    
    follow_path_axis_forward_map = {
        'POS_X':'FORWARD_X',
        'POS_Y':'FORWARD_Y',
        'POS_Z':'FORWARD_Z',
        'NEG_X':'TRACK_NEGATIVE_X',
        'NEG_Y':'TRACK_NEGATIVE_Y',
        'NEG_Z':'TRACK_NEGATIVE_Z',
    }
    follow_path_axis_up_map = { # TODO: check consistency
        'POS_X':('UP_Z', (0,0,0)),
        'POS_Y':('UP_X', (0,0,0)),
        'POS_Z':('UP_Y', (0,0,0)),
        'NEG_X':('UP_Z', (-90,0,0)),
        'NEG_Y':('UP_X', (0,-90,0)),
        'NEG_Z':('UP_Y', (0,0,-90)),
    }
    curve_deform_axis_map = {
        'POS_X':'POS_X',
        'POS_Y':'POS_Y',
        'POS_Z':'POS_Z',
        'NEG_X':'NEG_X',
        'NEG_Y':'NEG_Y',
        'NEG_Z':'NEG_Z',
    }
    driver_axis_map = {
        'POS_X':0,
        'POS_Y':1,
        'POS_Z':2,
        'NEG_X':0,
        'NEG_Y':1,
        'NEG_Z':2,
    }
    sign_axis_map = {
        'POS_X':+1,
        'POS_Y':+1,
        'POS_Z':+1,
        'NEG_X':-1,
        'NEG_Y':-1,
        'NEG_Z':-1,
    }
    vector_axis_map = {
        'POS_X':Vector((1,0,0)),
        'POS_Y':Vector((0,1,0)),
        'POS_Z':Vector((0,0,1)),
        'NEG_X':Vector((-1,0,0)),
        'NEG_Y':Vector((0,-1,0)),
        'NEG_Z':Vector((0,0,-1)),
    }
    
    def on_attachment_changed(self, context):
        self.attachment_update()
    
    attachment_template_type = 'MESH' | prop("Template type", "Template type", update=on_attachment_changed, items=[
        ('MESH', "Mesh", "Mesh"),
        ('OBJECT', "Object", "Object"),
        ('GROUP', "Group", "Group"),
    ])
    attachment_deform = True | prop("Deform geometry by curve", "Deform", update=on_attachment_changed)
    attachment_pos_absolute = 0.0 | prop("Absolute position", "Absolute position", update=on_attachment_changed, subtype='DISTANCE', unit='LENGTH', step=0.1, precision=3)
    attachment_pos_relative = 0.0 | prop("Relative position", "Relative position", update=on_attachment_changed, step=0.1, precision=3)
    attachment_angle = 0.0 | prop("Angle", "Angle", update=on_attachment_changed, subtype='ANGLE', unit='ROTATION')
    attachment_scale = 1.0 | prop("Scale", "Scale", update=on_attachment_changed, step=0.1, precision=3)
    attachment_forward_axis = 'POS_Z' | prop("Forward axis", "Forward axis", update=on_attachment_changed, items=[
        ('POS_X', "+X", "+X"),
        ('POS_Y', "+Y", "+Y"),
        ('POS_Z', "+Z", "+Z"),
        ('NEG_X', "-X", "-X"),
        ('NEG_Y', "-Y", "-Y"),
        ('NEG_Z', "-Z", "-Z"),
    ])
    attachment_array_use_length = False | prop("Use fixed length instead of array count", "Use length", update=on_attachment_changed)
    attachment_array_count = 1 | prop("Array count", "Array count", update=on_attachment_changed, min=1)
    attachment_array_length_const = 0.0 | prop("Fixed length", "Const length", update=on_attachment_changed, min=0.0, subtype='DISTANCE', unit='LENGTH', step=0.1, precision=3)
    attachment_array_length_factor = 0.0 | prop("Length proportional to curve", "Curve factor", update=on_attachment_changed, min=0.0, step=0.1, precision=3)
    attachment_array_offset_abs = 0.0 | prop("Absolute offset", "Absolute offset", update=on_attachment_changed, subtype='DISTANCE', unit='LENGTH', step=0.1, precision=3)
    attachment_array_offset_rel = 1.0 | prop("Relative offset", "Relative offset", update=on_attachment_changed, step=0.1, precision=3)
    
    @property
    def attachment_modifiers_possible(self):
        return (self.attachment_template_type != 'GROUP')
    
    @property
    def attachment_template_data_prop(self):
        attachment_obj = self.id_data
        if self.attachment_template_type == 'MESH':
            return (attachment_obj, "data")
        elif self.attachment_template_type == 'OBJECT':
            md_cap = self._get_modifier(attachment_obj, 'ARRAY', True, name="Cap")
            return (md_cap, "start_cap") # or end_cap, they're equivalent here
        elif self.attachment_template_type == 'GROUP':
            return (attachment_obj, "dupli_group")
        else:
            return (None, "")
    
    @property
    def can_edit_materials(self):
        attachment_obj = self.id_data
        mesh = attachment_obj.data
        if not mesh: return False
        degenerate_mesh = self._get_degenerate_mesh(True, "<Select a mesh>")
        return (mesh != degenerate_mesh)
    
    del _get
    del _set

@addon.Operator(idname="object.cable_reset_profile_settings", description="Reset Profile settings")
def cable_reset_profile_settings(self, context, event):
    cable_settings = context.object.cable_settings
    obj, curve = cable_settings.get_obj_curve()
    if not curve: return
    curve.bevel_object = None
    curve.use_fill_caps = False
    curve.extrude = 0.0
    curve.bevel_depth = 0.0
    curve.bevel_resolution = 0

@addon.Operator(idname="object.cable_reset_tweaks_settings", description="Reset Tweaks settings")
def cable_reset_tweaks_settings(self, context, event):
    cable_settings = context.object.cable_settings
    obj, curve = cable_settings.get_obj_curve()
    if not curve: return
    curve.taper_object = None
    curve.use_map_taper = False
    cable_settings.thickness = 0.0
    cable_settings.offset = -1.0
    curve.bevel_factor_start = 0.0
    curve.bevel_factor_end = 1.0
    if bevel_factor_mapping_exists:
        curve.bevel_factor_mapping_start = 'RESOLUTION'
        curve.bevel_factor_mapping_end = 'RESOLUTION'

@addon.Operator(idname="object.cable_attachment_add", description="Add cable attachment")
def cable_attachment_add(self, context, event):
    cable_settings = context.object.cable_settings
    obj, curve = cable_settings.get_obj_curve()
    if not curve: return
    cable_settings.attachment_add()

@addon.Operator(idname="object.cable_attachment_delete", description="Delete cable attachment")
def cable_attachment_delete(self, context, event, index=0):
    cable_settings = context.object.cable_settings
    obj, curve = cable_settings.get_obj_curve()
    if not curve: return
    cable_settings.attachment_delete(index)

@addon.Operator(idname="object.select_whole_subheirarchy", description="Select whole subhierarchy")
def select_whole_subheirarchy(self, context, event):
    selection = set()
    
    def gather_subheirarchy(parent):
        selection.add(parent)
        for child in parent.children:
            gather_subheirarchy(child)
    
    for obj in context.selected_objects:
        gather_subheirarchy(obj)
    
    # An object must be BOTH selectable AND visible in viewport to be copied/deleted correctly
    # (otherwise, the unselectable/invisible objects will be ignored by copying/deletion)
    for obj in selection:
        obj.hide = False
        obj.hide_select = False
        obj.select = True

@addon.Operator(idname="object.cable_unselect_children", description="Make wires/attachments non-selectable")
def cable_unselect_children(self, context, event):
    obj = context.object
    if not obj: return
    
    cable_settings = obj.cable_settings
    if not cable_settings.get_obj_curve(): return
    
    tags_hide = {"CABLE_EXTRAS", "LENGTH_CALC"}
    
    cable_objects = cable_settings.collect_cable_objects(include_self=False)
    for child in cable_objects:
        child.select = False
        child.hide_select = True
        if cable_objects.cable_settings.tag in tags_hide:
            child.hide = True

@addon.Operator(idname="object.cable_to_mesh", description="Convert cable to mesh")
def cable_to_mesh(self, context, event):
    obj = context.object
    if not obj: return
    
    cable_settings = obj.cable_settings
    if not cable_settings.get_obj_curve(): return
    
    if obj.mode != 'OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
    
    name = obj.name
    
    include_self = not ((cable_settings.is_wireframe or obj.hide) and obj.hide_render)
    cable_objects = cable_settings.collect_cable_objects(include_self=include_self, tags=CableSettingsPG.tags_visible)
    cable_objects = [cable_obj for cable_obj in cable_objects if not cable_obj.hide]
    
    mesh_baker = MeshBaker(
        scene=context.scene,
        include=cable_objects,
        selection=True,
        dupli=True,
        matrix=Matrix(obj.matrix_world),
        collect_materials=True,
        remove_doubles=0.0001,
    )
    mesh_baker.update()
    res_obj = mesh_baker.object('FORGET')
    mesh_baker.cleanup()
    
    def recursive_delete(parent):
        for child in parent.children:
            recursive_delete(child)
        
        try:
            bpy.context.scene.objects.unlink(parent)
            bpy.data.objects.remove(parent)
        except Exception:
            pass
    
    recursive_delete(obj)
    
    res_obj.name = name
    res_obj.data.name = name
    
    res_obj.select = True
    context.scene.objects.active = res_obj
    
    bpy.ops.ed.undo_push(message="Cable to mesh")

@addon.Operator(idname="object.cable_auto_twist", label="Auto twist curve")
class CableAutoTwistOperator:
    fix_start = True | prop("Fix start", "Fix start")
    fix_end = False | prop("Fix end", "Fix end")
    angle_start = 0.0 | prop("Start angle", "Start angle", subtype='ANGLE', unit='ROTATION')
    angle_end = 0.0 | prop("End angle", "End angle", subtype='ANGLE', unit='ROTATION')
    mode = 'CURVE' | prop("Angle interpretation", "Angle per", items=[
        # mapping distance along curve to control points can be complicated, especially for NURBS
        #('LENGTH', "Length", "Angle per unit length"),
        ('SEGMENT', "Segment", "Angle per curve segment"),
        ('CURVE', "Curve", "Angle per whole curve"),
    ])
    angle = 0.0 | prop("Angle", "Angle", subtype='ANGLE', unit='ROTATION')
    
    def execute(self, context):
        n_segments = len(self.points) - 1
        if self.fix_start and self.fix_end:
            angle0 = self.angle_start
            angle_delta = clamp_angle(self.angle_end - self.angle_start)
            twopi = math.pi*2
            n = round(abs(self.angle) / twopi)
            angle1 = angle0 + angle_delta + math.copysign(twopi * n, self.angle)
            angle_step = ((angle1 - angle0) / n_segments if n_segments > 0 else 0.0)
            print((math.degrees(angle0), math.degrees(angle1), math.degrees(angle_step)))
        elif self.mode == 'SEGMENT':
            angle_step = self.angle
            if self.fix_start:
                angle0 = self.angle_start
            else:
                angle0 = self.angle_end - angle_step * n_segments
                angle1 = self.angle_end
        elif self.mode == 'CURVE':
            angle_step = (self.angle / n_segments if n_segments > 0 else 0.0)
            if self.fix_start:
                angle0 = self.angle_start
            else:
                angle0 = self.angle_end - angle_step * n_segments
                angle1 = self.angle_end
        
        angle = angle0
        for point in self.points:
            point.tilt = angle
            angle += angle_step
        
        if self.fix_end and (not self.fix_start):
            self.points[-1].tilt = angle1 # to not accumulate errors
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        obj = context.object
        if not obj: return {'CANCELLED'}
        
        cable_settings = obj.cable_settings
        spline = cable_settings.get_spline()
        if not spline: return {'CANCELLED'}
        
        points = (spline.bezier_points if spline.type == 'BEZIER' else spline.points)
        if not points: return {'CANCELLED'}
        
        self.obj = obj
        self.cable_settings = cable_settings
        self.spline = spline
        self.points = points
        
        self.angle_start = points[0].tilt
        self.angle_end = points[-1].tilt
        
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        
        with layout.row():
            with layout.row(True):
                layout.prop(self, "fix_start", text="", icon='PINNED', toggle=True)
                layout.prop(self, "angle_start", text="Start")
            with layout.row(True):
                layout.prop(self, "fix_end", text="", icon='PINNED', toggle=True)
                layout.prop(self, "angle_end", text="End")
        
        with layout.row():
            layout.prop(self, "angle", text="Angle")
            with layout.row()(alignment='CENTER'):
                layout.label(text="per")
            layout.prop(self, "mode", text="")

addon.type_extend("Object", "cable_settings", CableSettingsPG)

prev_template_ids = None
prev_material_ids = None

@addon.scene_update_post
def scene_update_post(scene):
    global prev_template_ids, prev_material_ids
    
    obj = bpy.context.object
    if not obj: return
    cable_settings = obj.cable_settings
    if not cable_settings.get_spline(): return
    
    cable_settings.propagate_layers_to_children()
    
    material_ids = cable_settings.wire_material_ids()
    if prev_material_ids != material_ids:
        cable_settings.wire_update()
    prev_material_ids = material_ids
    
    template_ids = cable_settings.attachment_template_ids()
    if prev_template_ids != template_ids:
        cable_settings.attachment_update_all()
    prev_template_ids = template_ids

def register():
    addon.register()

def unregister():
    addon.unregister()
