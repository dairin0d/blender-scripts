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
    "name": "Batch Operations",
    "description": "Batch control of modifiers, etc.",
    "author": "dairin0d",
    "version": (0, 1, 0),
    "blender": (2, 7, 0),
    "location": "View3D > Batch category in Tools panel",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "",
    "category": "3D View"}
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
from {0}dairin0d.utils_ui import NestedLayout, ui_context_under_coord
from {0}dairin0d.bpy_inspect import prop, BlRna
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

addon = AddonManager()

# moth3r asks to be able to add Batch panel also to the right shelf
# TODO: copy/paste modifiers; constraints; materials (+completely remove immediately)

refresh_interval = 0.5

# adapted from the Copy Attributes Menu addon
def copyattrs(src, dst, filter=""):
    for attr in dir(src):
        if attr.find(filter) > -1:
            try:
                setattr(dst, attr, getattr(src, attr))
            except:
                pass

def attrs_to_dict(obj):
    d = {}
    for name in dir(obj):
        if not name.startswith("_"):
            d[name] = getattr(obj, name)
    return d

def dict_to_attrs(obj, d):
    for name, value in d.items():
        if not name.startswith("_"):
            setattr(obj, name, value)

def copy_modifiers_to_selection(obj, context):
    for obj2 in context.selected_objects:
        if obj2 == obj:
            continue
        
        obj2.modifiers.clear()
        
        if not obj:
            continue
        
        for src in obj.modifiers:
            md = obj2.modifiers.new(src.name, src.type)
            copyattrs(src, md)

@addon.Operator(idname="view3d.pick_modifiers")
def Pick_Modifiers(self, context, event):
    """Pick modifier(s) from the object under mouse"""
    
    context.window.cursor_modal_set('EYEDROPPER')
    
    while True:
        self, context, event = yield {'RUNNING_MODAL'}
        cancel = (event.type in {'ESC', 'RIGHTMOUSE'})
        confirm = (event.type == 'LEFTMOUSE') and (event.value == 'PRESS')
        
        mouse = Vector((event.mouse_x, event.mouse_y))
        ui_context = ui_context_under_coord(mouse.x, mouse.y, 1)
        
        raycast_result = None
        if ui_context:
            if ui_context.area.type == 'VIEW_3D':
                if ui_context.region_data:
                    sv = SmartView3D(ui_context)
                    mouse_region = mouse - sv.region_rect()[0]
                    ray = sv.ray(mouse_region)
                    raycast_result = context.scene.ray_cast(*ray)
        
        obj = None
        if raycast_result and raycast_result[0]:
            obj = raycast_result[1]
        
        txt = ""
        if obj:
            txt = ", ".join(
                md.bl_rna.name.replace(" Modifier", "")
                for md in obj.modifiers)
        context.area.header_text_set(txt)
        
        if cancel or confirm:
            if confirm:
                bpy.ops.ed.undo_push(message="Pick Modifiers")
                copy_modifiers_to_selection(obj, context)
            context.area.header_text_set()
            context.window.cursor_modal_restore()
            return ({'FINISHED'} if confirm else {'CANCELLED'})

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

@addon.Operator(idname="object.batch_modifier_copy")
def Batch_Copy_Modifiers(self, context):
    """Copy modifier(s) from the selected objects"""
    obj = context.active_object
    if obj:
        md_infos = [BlRna.serialize(md) for md in obj.modifiers]
        json_data = {"content":"Blender:object.modifiers", "items":md_infos}
        wm = context.window_manager
        wm.clipboard = json.dumps(json_data)

@addon.Operator(idname="object.batch_modifier_paste", options={'REGISTER', 'UNDO'})
def Batch_Paste_Modifiers(self, context):
    """Paste modifier(s) to the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Paste Modifiers")
    
    wm = context.window_manager
    try:
        json_data = json.loads(wm.clipboard)
        assert json_data["content"] == "Blender:object.modifiers"
    except:
        return
    
    for obj in context.selected_objects:
        obj.modifiers.clear()
    
    md_infos = json_data.get("items", ())
    for md_info in md_infos:
        idname = md_info.get("type")
        if not idname:
            continue
        md_info.pop("type", None)
        name = md_info.get("name", idname.capitalize())
        md_info.pop("name", None)
        for obj in context.selected_objects:
            md = obj.modifiers.new(name, idname)
            BlRna.deserialize(md, md_info)

@addon.Operator(idname="object.batch_modifier_add", options={'REGISTER', 'UNDO'})
def Batch_Add_Modifiers(self, context, modifier=""):
    """Add modifier(s) to the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Add Modifiers")
    
    for obj in context.selected_objects:
        md = obj.modifiers.new(modifier.capitalize(), modifier)

@addon.Operator(idname="object.batch_modifier_ensure", options={'REGISTER', 'UNDO'})
def Batch_Ensure_Modifiers(self, context, modifier=""):
    """Ensure modifier(s) for the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Ensure Modifiers")
    
    if "," in modifier:
        modifiers = [m.strip() for m in modifier.split(",")]
    else:
        modifiers = [modifier.strip()]
    
    active_obj = context.active_object
    
    for modifier in modifiers:
        if not modifier:
            continue
        
        src = None
        if active_obj:
            for md in active_obj.modifiers:
                if (md.type == modifier):
                    src = md
                    break
        
        for obj in context.selected_objects:
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

@addon.Operator(idname="object.batch_modifier_apply", options={'REGISTER', 'UNDO'})
def Batch_Apply_Modifiers(self, context, modifier=""):
    """Apply modifier(s) and remove from the stack(s)"""
    bpy.ops.ed.undo_push(message="Batch Apply Modifiers")
    
    active_obj = context.active_object
    for obj in context.selected_objects:
        context.scene.objects.active = obj
        for md in obj.modifiers:
            if (not modifier) or (md.type == modifier):
                bpy.ops.object.modifier_apply(modifier=md.name) # not type or idname!
    context.scene.objects.active = active_obj

@addon.Operator(idname="object.batch_modifier_remove", options={'REGISTER', 'UNDO'})
def Batch_Remove_Modifiers(self, context, modifier=""):
    """Remove modifier(s) from the selected objects"""
    bpy.ops.ed.undo_push(message="Batch Remove Modifiers")
    
    for obj in context.selected_objects:
        for md in tuple(obj.modifiers):
            if (not modifier) or (md.type == modifier):
                obj.modifiers.remove(md)

@addon.PropertyGroup
class ModifierPG:
    idname = "" | prop()
    
    initialized = False | prop()
    
    def gen_show_update(name):
        def update(self, context):
            if not self.initialized:
                return
            
            message = self.bl_rna.properties[name].description
            bpy.ops.ed.undo_push(message=message)
            
            value = getattr(self, name)[0]
            for obj in context.selected_objects:
                for md in obj.modifiers:
                    if (not self.idname) or (md.type == self.idname):
                        setattr(md, name, value)
        
        return update
    
    show_expanded = (True, True) | prop("Are modifier(s) expanded in the UI",
        update=gen_show_update("show_expanded"))
    show_render = (True, True) | prop("Use modifier(s) during render",
        update=gen_show_update("show_render"))
    show_viewport = (True, True) | prop("Display modifier(s) in viewport",
        update=gen_show_update("show_viewport"))
    show_in_editmode = (True, True) | prop("Display modifier(s) in edit mode",
        update=gen_show_update("show_in_editmode"))
    show_on_cage = (True, True) | prop("Adjust edit cage to modifier(s) result",
        update=gen_show_update("show_on_cage"))
    
    def from_info_toggle(self, info, name):
        ivalue = info[name]
        value = ((ivalue[0] >= 0), ivalue[1])
        setattr(self, name, value)

@addon.PropertyGroup
class ModifiersPG:
    all_types_enum = (bpy.ops.object.
        modifier_add.get_rna().bl_rna.
        properties["type"].enum_items)
    all_types_enum = BlRna.serialize_value(all_types_enum)
    
    items = [ModifierPG] | prop()
    
    clock = 0.0 | prop()
    
    all_idnames = "" | prop()
    
    remaining_items = []
    
    def refresh(self, context):
        if time.clock() < self.clock:
            return # prevent refresh-each-frame situation
        self.clock = time.clock() + refresh_interval
        
        infos = {}
        for obj in context.selected_objects:
            for md in obj.modifiers:
                self.extract_info(infos, md, "", "", "")
                self.extract_info(infos, md)
        if not infos:
            self.extract_info(infos, None, "", "", "")
        
        sorted_keys = sorted(infos.keys())
        self.all_idnames = ",".join(sorted_keys)
        
        current_keys = set(infos.keys())
        ModifiersPG.remaining_items = [enum_item
            for enum_item in ModifiersPG.all_types_enum
            if enum_item[0] not in current_keys]
        
        self.items.clear()
        for key in sorted_keys:
            info = infos[key]
            item = self.items.add()
            item.name = info["name"].replace(" Modifier", "")
            item.idname = info["type"]
            item.from_info_toggle(info, "show_expanded")
            item.from_info_toggle(info, "show_render")
            item.from_info_toggle(info, "show_viewport")
            item.from_info_toggle(info, "show_in_editmode")
            item.from_info_toggle(info, "show_on_cage")
            item.initialized = True
    
    def extract_info(self, infos, md, md_type=None, name=None, identifier=None):
        if md_type is None:
            md_type = md.type
        
        info = infos.get(md_type)
        
        if info is None:
            if name is None:
                name = md.bl_rna.name
            
            if identifier is None:
                identifier = md.bl_rna.identifier
            
            info = dict(type=md_type, name=name, identifier=identifier)
            infos[md_type] = info
        
        self.extract_info_toggle(info, md, "show_expanded")
        self.extract_info_toggle(info, md, "show_render")
        self.extract_info_toggle(info, md, "show_viewport")
        self.extract_info_toggle(info, md, "show_in_editmode")
        self.extract_info_toggle(info, md, "show_on_cage")
    
    def extract_info_toggle(self, info, md, name):
        if md is None:
            info[name] = [False, False]
            return
        
        value = (1 if getattr(md, name) else -1)
        ivalue = info.get(name)
        if ivalue is None:
            info[name] = [value, True]
        else:
            if (value * ivalue[0]) < 0:
                ivalue[1] = False
            ivalue[0] += value
    
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
    
    def draw_toggle(self, layout, item, name, icon):
        with layout.row(True)(alert=not getattr(item, name)[1]):
            layout.prop(item, name, icon=icon, text="", index=0, toggle=True)
    
    def draw(self, layout):
        all_enabled = (len(self.items) > 1)
        with layout.column(True)(enabled=all_enabled):
            for item in self.items:
                with layout.row(True):
                    #icon = ('TRIA_DOWN' if item.show_expanded[0] else 'TRIA_RIGHT')
                    #self.draw_toggle(layout, item, "show_expanded", icon)
                    self.draw_toggle(layout, item, "show_render", 'SCENE')
                    self.draw_toggle(layout, item, "show_viewport", 'VISIBLE_IPO_ON')
                    self.draw_toggle(layout, item, "show_in_editmode", 'EDITMODE_HLT')
                    self.draw_toggle(layout, item, "show_on_cage", 'MESH_DATA')
                    
                    icon = self.modifier_icons.get(item.idname, 'MODIFIER')
                    op = layout.operator("object.batch_modifier_ensure", text="", icon=icon)
                    op.modifier = item.idname or self.all_idnames
                    
                    op = layout.operator("object.batch_modifier_apply", text=(item.name or "(All)"))
                    op.modifier = item.idname
                    
                    op = layout.operator("object.batch_modifier_remove", icon='X', text="")
                    op.modifier = item.idname

@addon.Panel
class VIEW3D_PT_batch_modifiers:#(bpy.types.Panel):
    bl_category = "Batch"
    bl_context = "objectmode"
    bl_label = "Modifiers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def draw_header(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        batch_modifiers.refresh(context)
        with layout.row(True):
            with layout.row():
                layout.menu("OBJECT_MT_batch_modifier_add", icon='ZOOMIN', text="")
            #with layout.row():
            #    layout.operator("view3d.pick_modifiers", icon='EYEDROPPER', text="")
            #with layout.row():
            #    layout.operator("object.batch_modifier_copy", icon='COPYDOWN', text="")
            #with layout.row():
            #    layout.operator("object.batch_modifier_paste", icon='PASTEDOWN', text="")
            layout.operator("view3d.pick_modifiers", icon='EYEDROPPER', text="")
            layout.operator("object.batch_modifier_copy", icon='COPYDOWN', text="")
            layout.operator("object.batch_modifier_paste", icon='PASTEDOWN', text="")
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        batch_modifiers = addon.external.modifiers
        batch_modifiers.refresh(context)
        batch_modifiers.draw(layout)

addon.External.modifiers = ModifiersPG | -prop()

# TODO: copy, paste ?

def register():
    addon.register()

def unregister():
    addon.unregister()
