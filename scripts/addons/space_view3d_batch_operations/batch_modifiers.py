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

import time
import json

from mathutils import Vector

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_view3d import SmartView3D
from {0}dairin0d.utils_userinput import KeyMapUtils
from {0}dairin0d.utils_ui import NestedLayout
from {0}dairin0d.bpy_inspect import prop, BlRna
from {0}dairin0d.utils_accumulation import Aggregator, aggregated
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

from .batch_common import copyattrs, attrs_to_dict, dict_to_attrs, Pick_Base, LeftRightPanel, round_to_bool

addon = AddonManager()

# =============================== MODIFIERS ================================ #
#============================================================================#
modifier_icons = {
    'MESH_CACHE':'MOD_MESHDEFORM',
    'UV_PROJECT':'MOD_UVPROJECT',
    'UV_WARP':'MOD_UVPROJECT',
    'VERTEX_WEIGHT_EDIT':'MOD_VERTEX_WEIGHT',
    'VERTEX_WEIGHT_MIX':'MOD_VERTEX_WEIGHT',
    'VERTEX_WEIGHT_PROXIMITY':'MOD_VERTEX_WEIGHT',
    'ARRAY':'MOD_ARRAY',
    'BEVEL':'MOD_BEVEL',
    'BOOLEAN':'MOD_BOOLEAN',
    'BUILD':'MOD_BUILD',
    'DECIMATE':'MOD_DECIM',
    'EDGE_SPLIT':'MOD_EDGESPLIT',
    'MASK':'MOD_MASK',
    'MIRROR':'MOD_MIRROR',
    'MULTIRES':'MOD_MULTIRES',
    'REMESH':'MOD_REMESH',
    'SCREW':'MOD_SCREW',
    'SKIN':'MOD_SKIN',
    'SOLIDIFY':'MOD_SOLIDIFY',
    'SUBSURF':'MOD_SUBSURF',
    'TRIANGULATE':'MOD_TRIANGULATE',
    'WIREFRAME':'MOD_WIREFRAME',
    'ARMATURE':'MOD_ARMATURE',
    'CAST':'MOD_CAST',
    'CURVE':'MOD_CURVE',
    'DISPLACE':'MOD_DISPLACE',
    'HOOK':'HOOK',
    'LAPLACIANSMOOTH':'MOD_SMOOTH',
    'LAPLACIANDEFORM':'MOD_MESHDEFORM',
    'LATTICE':'MOD_LATTICE',
    'MESH_DEFORM':'MOD_MESHDEFORM',
    'SHRINKWRAP':'MOD_SHRINKWRAP',
    'SIMPLE_DEFORM':'MOD_SIMPLEDEFORM',
    'SMOOTH':'MOD_SMOOTH',
    'WARP':'MOD_WARP',
    'WAVE':'MOD_WAVE',
    'CLOTH':'MOD_CLOTH',
    'COLLISION':'MOD_PHYSICS',
    'DYNAMIC_PAINT':'MOD_DYNAMICPAINT',
    'EXPLODE':'MOD_EXPLODE',
    'FLUID_SIMULATION':'MOD_FLUIDSIM',
    'OCEAN':'MOD_OCEAN',
    'PARTICLE_INSTANCE':'MOD_PARTICLES',
    'PARTICLE_SYSTEM':'MOD_PARTICLES',
    'SMOKE':'MOD_SMOKE',
    'SOFT_BODY':'MOD_SOFT',
    'SURFACE':'MODIFIER',
}

class BatchModifiers:
    clipbuffer = None
    
    @classmethod
    def clean_name(cls, md):
        return md.bl_rna.name.replace(" Modifier", "")
    
    @classmethod
    def set_attr(cls, name, value, objects, modifier=""):
        for obj in objects:
            for md in obj.modifiers:
                if (not modifier) or (md.type == modifier):
                    setattr(md, name, value)
    
    @classmethod
    def clear(cls, objects):
        for obj in objects:
            obj.modifiers.clear()
    
    @classmethod
    def add(cls, objects, modifier):
        for obj in objects:
            md = obj.modifiers.new(modifier.capitalize(), modifier)
    
    @classmethod
    def ensure(cls, active_obj, objects, modifier=""):
        if "\n" in modifier:
            modifiers = [m.strip() for m in modifier.split("\n")]
        else:
            modifiers = [modifier.strip()]
        
        for modifier in modifiers:
            if not modifier:
                continue
            
            src = None
            if active_obj:
                for md in active_obj.modifiers:
                    if (md.type == modifier):
                        src = md
                        break
            
            for obj in objects:
                has_modifier = False
                for md in obj.modifiers:
                    if (md.type == modifier):
                        has_modifier = True
                        #break
                        if src:
                            copyattrs(src, md)
                
                if not has_modifier:
                    md = obj.modifiers.new(modifier.capitalize(), modifier)
                    if src:
                        copyattrs(src, md)
    
    @classmethod
    def apply(cls, objects, scene, modifier=""):
        active_obj = scene.objects.active
        for obj in objects:
            scene.objects.active = obj
            for md in obj.modifiers:
                if (not modifier) or (md.type == modifier):
                    bpy.ops.object.modifier_apply(modifier=md.name) # not type or idname!
        scene.objects.active = active_obj
    
    @classmethod
    def remove(cls, objects, modifier=""):
        for obj in objects:
            for md in tuple(obj.modifiers):
                if (not modifier) or (md.type == modifier):
                    obj.modifiers.remove(md)
    
    @classmethod
    def copy(cls, active_obj):
        if not active_obj:
            cls.clipbuffer = []
        else:
            cls.clipbuffer = [attrs_to_dict(md) for md in active_obj.modifiers]
    
    @classmethod
    def paste(cls, objects):
        md_infos = cls.clipbuffer
        if md_infos is None: return
        
        cls.clear(objects)
        
        for md_info in md_infos:
            idname = md_info.get("type")
            if not idname: continue
            
            name = md_info.get("name", idname.capitalize())
            
            md_info.pop("type", None)
            md_info.pop("name", None)
            for obj in objects:
                md = obj.modifiers.new(name, idname)
                dict_to_attrs(md, md_info)

#============================================================================#
@addon.Menu(idname="OBJECT_MT_batch_modifier_add")
def OBJECT_MT_batch_modifier_add(self, context):
    """Add modifier(s) to the selected objects"""
    layout = NestedLayout(self.layout)
    for item in ModifiersPG.remaining_items:
        idname = item[0]
        name = item[1]
        icon = ModifiersPG.modifier_icons.get(idname, 'MODIFIER')
        op = layout.operator("object.batch_modifier_add", text=name, icon=icon)
        op.modifier = idname

@addon.Operator(idname="view3d.pick_modifiers")
class Pick_Modifiers(Pick_Base):
    """Pick modifier(s) from the object under mouse"""
    
    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT')
    
    def obj_to_info(self, obj):
        txt = ", ".join(BatchModifiers.clean_name(md) for md in obj.modifiers)
        return (txt or "<No modifiers>")
    
    def on_confirm(self, context, obj):
        bpy.ops.ed.undo_push(message="Pick Modifiers")
        
        BatchModifiers.copy(obj)
        self.report({'INFO'}, "Modifiers copied")
        
        BatchModifiers.paste(context.selected_objects)

@addon.Operator(idname="object.batch_modifier_copy")
def Batch_Copy_Modifiers(self, context, event):
    """Copy modifier(s) from the selected objects"""
    if not context.object: return
    BatchModifiers.copy(context.object)
    self.report({'INFO'}, "Modifiers copied")

@addon.Operator(idname="object.batch_modifier_paste", options={'REGISTER', 'UNDO'})
def Batch_Paste_Modifiers(self, context, event):
    """Paste modifier(s) to the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Paste Modifiers")
    BatchModifiers.paste(context.selected_objects)

@addon.Operator(idname="object.batch_modifier_add", options={'REGISTER', 'UNDO'})
def Batch_Add_Modifiers(self, context, event, modifier=""):
    """Add modifier(s) to the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Add Modifiers")
    BatchModifiers.add(context.selected_objects, modifier)

@addon.Operator(idname="object.batch_modifier_ensure", options={'REGISTER', 'UNDO'})
def Batch_Ensure_Modifiers(self, context, event, modifier=""):
    """Ensure modifier(s) for the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Ensure Modifiers")
    BatchModifiers.ensure(context.object, context.selected_objects, modifier)

@addon.Operator(idname="object.batch_modifier_apply", options={'REGISTER', 'UNDO'})
def Batch_Apply_Modifiers(self, context, event, modifier=""):
    """Apply modifier(s) and remove from the stack(s)"""
    bpy.ops.ed.undo_push(message="Batch Apply Modifiers")
    BatchModifiers.apply(context.selected_objects, context.scene, modifier)

@addon.Operator(idname="object.batch_modifier_remove", options={'REGISTER', 'UNDO'})
def Batch_Remove_Modifiers(self, context, event, modifier=""):
    """Remove modifier(s) from the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Remove Modifiers")
    BatchModifiers.remove(context.selected_objects, modifier)

class ModifierAggregateInfo:
    def __init__(self, type, name, identifier):
        self.type = type
        self.name = name
        self.identifier = identifier
        self.count = 0
        self.show_expanded = Aggregator('NUMBER', {"same", "mean"}, int)
        self.show_render = Aggregator('NUMBER', {"same", "mean"}, int)
        self.show_viewport = Aggregator('NUMBER', {"same", "mean"}, int)
        self.show_in_editmode = Aggregator('NUMBER', {"same", "mean"}, int)
        self.show_on_cage = Aggregator('NUMBER', {"same", "mean"}, int)
    
    def fill_item(self, item):
        item.name = self.name.replace(" Modifier", "")
        item.idname = self.type
        item.count = self.count
        self.fill_aggr(item, "show_expanded", "mean", round_to_bool)
        self.fill_aggr(item, "show_render", "mean", round_to_bool)
        self.fill_aggr(item, "show_viewport", "mean", round_to_bool)
        self.fill_aggr(item, "show_in_editmode", "mean", round_to_bool)
        self.fill_aggr(item, "show_on_cage", "mean", round_to_bool)
        item.user_editable = True
    
    def fill_aggr(self, item, name, query, convert=None):
        aggr = getattr(self, name)
        value = getattr(aggr, query)
        if convert is not None: value = convert(value)
        setattr(item, name, value)
        item[name+":same"] = aggr.same
    
    @classmethod
    def collect_info(cls, modifiers):
        infos = {}
        for md in modifiers:
            cls.extract_info(infos, md, "", "", "")
            cls.extract_info(infos, md)
        sorted_keys = sorted(infos.keys())
        all_idnames = "\n".join(sorted_keys)
        return infos, sorted_keys, all_idnames
    
    @classmethod
    def extract_info(cls, infos, md, md_type=None, name=None, identifier=None):
        if md_type is None: md_type = md.type
        
        info = infos.get(md_type)
        
        if info is None:
            if name is None: name = md.bl_rna.name
            if identifier is None: identifier = md.bl_rna.identifier
            
            info = cls(md_type, name, identifier)
            infos[md_type] = info
        
        info.count += 1
        info.show_expanded.add(md.show_expanded)
        info.show_render.add(md.show_render)
        info.show_viewport.add(md.show_viewport)
        info.show_in_editmode.add(md.show_in_editmode)
        info.show_on_cage.add(md.show_on_cage)

@addon.PropertyGroup
class ModifierPG:
    idname = "" | prop()
    count = 0 | prop()
    excluded = False | prop()
    user_editable = False | prop()
    
    def gen_show_update(name):
        def update(self, context):
            if not self.user_editable: return
            message = self.bl_rna.properties[name].description
            value = getattr(self, name)
            bpy.ops.ed.undo_push(message=message)
            BatchModifiers.set_attr(name, value, context.selected_objects, self.idname)
        return update
    
    show_expanded = True | prop("Are modifier(s) expanded in the UI", update=gen_show_update("show_expanded"))
    show_render = True | prop("Use modifier(s) during render", update=gen_show_update("show_render"))
    show_viewport = True | prop("Display modifier(s) in viewport", update=gen_show_update("show_viewport"))
    show_in_editmode = True | prop("Display modifier(s) in edit mode", update=gen_show_update("show_in_editmode"))
    show_on_cage = True | prop("Adjust edit cage to modifier(s) result", update=gen_show_update("show_on_cage"))

@addon.PropertyGroup
class ModifiersPG:
    all_types_enum = BlRna.serialize_value(bpy.ops.object.
        modifier_add.get_rna().bl_rna.
        properties["type"].enum_items)
    
    items = [ModifierPG] | prop()
    
    all_idnames = "" | prop()
    
    remaining_items = []
    
    paste_mode = 'SET' | prop("Copy/Paste mode", items=[
        ('SET', "Replace", "Replace", 'ROTACTIVE'),
        ('OR', "Add", "Union", 'ROTATECOLLECTION'),
        ('AND', "Filter", "Intersection", 'ROTATECENTER'),
    ])
    show_for = 'SELECTION' | prop("Show summary for", items=[
        ('SELECTION', "Selection", "Selection", 'RESTRICT_SELECT_OFF'), # EDIT OBJECT_DATA UV_SYNC_SELECT
        ('VISIBLE', "Visible", "Visible", 'RESTRICT_VIEW_OFF'),
        ('LAYER', "Layer", "Layer", 'RENDERLAYERS'),
        ('SCENE', "Scene", "Scene", 'SCENE_DATA'),
        ('FILE', "File", "File", 'FILE_BLEND'),
        #('DATA', "Data", "Data", 'BLENDER'),
    ])
    apply_options = {'CONVERT_TO_MESH', 'MAKE_SINGLE_USER'} | prop("Apply Modifier options", items=[
        ('CONVERT_TO_MESH', "Convert to mesh", "Convert to mesh", 'OUTLINER_OB_MESH'),
        ('MAKE_SINGLE_USER', "Make signle user", "Make signle user", 'UNLINKED'), # COPY_ID UNLINKED
    ])
    
    def refresh(self, context):
        infos, sorted_keys, self.all_idnames = ModifierAggregateInfo.collect_info(
            md for obj in context.selected_objects for md in obj.modifiers)
        
        current_keys = set(infos.keys())
        ModifiersPG.remaining_items = [enum_item
            for enum_item in ModifiersPG.all_types_enum
            if enum_item[0] not in current_keys]
        ModifiersPG.remaining_items.sort(key=lambda item:item[1])
        
        self.items.clear()
        for key in sorted_keys:
            infos[key].fill_item(self.items.add())
    
    def draw_toggle(self, layout, item, name, icon):
        with layout.row(True)(alert=not item[name+":same"]):
            layout.prop(item, name, icon=icon, text="", toggle=True)
    
    def draw(self, layout):
        with layout.column(True):
            for item in self.items:
                with layout.row(True):
                    #icon = ('TRIA_DOWN' if item.show_expanded[0] else 'TRIA_RIGHT')
                    #self.draw_toggle(layout, item, "show_expanded", icon)
                    self.draw_toggle(layout, item, "show_render", 'SCENE')
                    self.draw_toggle(layout, item, "show_viewport", 'VISIBLE_IPO_ON')
                    self.draw_toggle(layout, item, "show_in_editmode", 'EDITMODE_HLT')
                    self.draw_toggle(layout, item, "show_on_cage", 'MESH_DATA')
                    
                    icon = modifier_icons.get(item.idname, 'MODIFIER')
                    op = layout.operator("object.batch_modifier_ensure", text="", icon=icon)
                    op.modifier = item.idname or self.all_idnames
                    
                    text = "{} ({})".format(item.name or "(All)", item.count)
                    op = layout.operator("object.batch_modifier_apply", text=text)
                    op.modifier = item.idname
                    
                    op = layout.operator("object.batch_modifier_remove", icon='X', text="")
                    op.modifier = item.idname

@addon.Menu
class VIEW3D_MT_batch_modifiers_options_paste_mode:
    bl_label = "Copy/Paste mode"
    bl_description = "Copy/Paste mode"
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        layout.props_enum(batch_modifiers, "paste_mode")
        #layout.prop(batch_modifiers, "paste_mode", expand=True)

@addon.Menu
class VIEW3D_MT_batch_modifiers_options_show_for:
    bl_label = "Search in"
    bl_description = "Search in"
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        layout.props_enum(batch_modifiers, "show_for")
        #layout.prop(batch_modifiers, "show_for", expand=True)

@addon.Menu
class VIEW3D_MT_batch_modifiers_options_apply_options:
    bl_label = "Apply Modifier"
    bl_description = "Apply Modifier options"
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        layout.props_enum(batch_modifiers, "apply_options")
        #layout.prop(batch_modifiers, "apply_options", expand=True)

@addon.Menu
class VIEW3D_MT_batch_modifiers_options:
    bl_label = "Options"
    bl_description = "Options"
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        
        with layout.column():
            #layout.prop_enum(batch_modifiers, "paste_mode")
            #layout.prop_enum(batch_modifiers, "show_for")
            #layout.props_enum(batch_modifiers, "paste_mode")
            #layout.props_enum(batch_modifiers, "show_for")
            #layout.prop_menu_enum(batch_modifiers, "paste_mode")
            #layout.prop_menu_enum(batch_modifiers, "show_for")
            #layout.prop(batch_modifiers, "paste_mode", text="", expand=True)
            #layout.prop(batch_modifiers, "show_for", text="", expand=True)
            layout.menu("VIEW3D_MT_batch_modifiers_options_paste_mode", icon='PASTEDOWN')
            layout.menu("VIEW3D_MT_batch_modifiers_options_show_for", icon='VIEWZOOM')
            layout.menu("VIEW3D_MT_batch_modifiers_options_apply_options", icon='MODIFIER')
            # convert to mesh on apply OUTLINER_OB_MESH
            # make data single-user before applying COPY_ID UNLINKED
            # NLA_PUSHDOWN MODIFIER

@LeftRightPanel
class VIEW3D_PT_batch_modifiers:
    bl_category = "Batch"
    bl_context = "objectmode"
    bl_label = "Batch Modifiers"
    bl_space_type = 'VIEW_3D'
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        
        with layout.row():
            with layout.row(True):
                layout.menu("OBJECT_MT_batch_modifier_add", icon='ZOOMIN', text="")
                layout.operator("view3d.pick_modifiers", icon='EYEDROPPER', text="")
                layout.operator("object.batch_modifier_copy", icon='COPYDOWN', text="")
                layout.operator("object.batch_modifier_paste", icon='PASTEDOWN', text="")
            layout.menu("VIEW3D_MT_batch_modifiers_options", icon='SCRIPTPLUGINS', text="")
        
        batch_modifiers.draw(layout)

addon.External.modifiers = ModifiersPG | -prop()
