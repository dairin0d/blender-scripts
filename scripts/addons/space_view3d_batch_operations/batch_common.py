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
from {0}dairin0d.utils_ui import NestedLayout, tag_redraw
from {0}dairin0d.bpy_inspect import prop, BlRna, BlEnums
from {0}dairin0d.utils_accumulation import Aggregator, VectorAggregator
from {0}dairin0d.utils_blender import ChangeMonitor
from {0}dairin0d.utils_addon import AddonManager

""".format(dairin0d_location))

addon = AddonManager()

idnames_separator = "\t"

def round_to_bool(v):
    return (v > 0.5) # bool(round(v))

def has_common_layers(obj, scene):
    return any(l0 and l1 for l0, l1 in zip(obj.layers, scene.layers))

def is_visible(obj, scene):
    return (not obj.hide) and has_common_layers(obj, scene)

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
            try:
                setattr(obj, name, value)
            except:
                pass

class PatternRenamer:
    before = "\u2190"
    after = "\u2192"
    whole = "\u2194"
    
    @classmethod
    def is_pattern(cls, value):
        return (cls.before in value) or (cls.after in value) or (cls.whole in value)
    
    @classmethod
    def make(cls, subseq, subseq_starts, subseq_ends):
        pattern = subseq
        if (not subseq_starts): pattern = cls.before + pattern
        if (not subseq_ends): pattern = pattern + cls.after
        if (pattern == cls.before+cls.after): pattern = cls.whole
        return pattern
    
    @classmethod
    def apply(cls, value, src_pattern, pattern):
        middle = src_pattern.lstrip(cls.before).rstrip(cls.after).rstrip(cls.whole)
        if middle not in value: return value # pattern not applicable
        i_mid = value.index(middle)
        
        sL, sC, sR = "", value, ""
        
        if src_pattern.startswith(cls.before):
            if middle:
                sL = value[:i_mid]
        
        if src_pattern.endswith(cls.after):
            if middle:
                sR = value[i_mid+len(middle):]
        
        return pattern.replace(cls.before, sL).replace(cls.after, sR).replace(cls.whole, sC)
    
    @classmethod
    def apply_to_attr(cls, obj, attr_name, pattern, src_pattern):
        setattr(obj, attr_name, cls.apply(getattr(obj, attr_name), src_pattern, pattern))

class Pick_Base:
    def invoke(self, context, event):
        context.window.cursor_modal_set('EYEDROPPER')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        cancel = (event.type in {'ESC', 'RIGHTMOUSE'})
        confirm = (event.type == 'LEFTMOUSE') and (event.value == 'PRESS')
        
        mouse = Vector((event.mouse_x, event.mouse_y))
        
        raycast_result = None
        sv = SmartView3D((mouse.x, mouse.y, 0))
        if sv:
            #raycast_result = sv.ray_cast(mouse, coords='WINDOW')
            select_result = sv.select(mouse, coords='WINDOW')
            raycast_result = (bool(select_result[0]), select_result[0])
        
        obj = None
        if raycast_result and raycast_result[0]:
            obj = raycast_result[1]
        
        txt = (self.obj_to_info(obj) if obj else "")
        context.area.header_text_set(txt)
        
        if cancel or confirm:
            if confirm:
                self.on_confirm(context, obj)
            context.area.header_text_set()
            context.window.cursor_modal_restore()
            return ({'FINISHED'} if confirm else {'CANCELLED'})
        return {'RUNNING_MODAL'}

def LeftRightPanel(cls=None, **kwargs):
    def AddPanels(cls, kwargs):
        doc = cls.__doc__
        name = kwargs.get("bl_idname") or kwargs.get("idname") or cls.__name__
        
        # expected either class or function
        if not isinstance(cls, type):
            cls = type(name, (), dict(__doc__=doc, draw=cls))
        
        poll = getattr(cls, "poll", None)
        if poll:
            poll_left = classmethod(lambda cls, context: addon.preferences.use_panel_left and poll(cls, context))
            poll_right = classmethod(lambda cls, context: addon.preferences.use_panel_right and poll(cls, context))
        else:
            poll_left = classmethod(lambda cls, context: addon.preferences.use_panel_left)
            poll_right = classmethod(lambda cls, context: addon.preferences.use_panel_right)
        
        @addon.Panel(**kwargs)
        class LeftPanel(cls):
            bl_idname = name + "_left"
            bl_region_type = 'TOOLS'
            poll = poll_left
        
        @addon.Panel(**kwargs)
        class RightPanel(cls):
            bl_idname = name + "_right"
            bl_region_type = 'UI'
            poll = poll_right
        
        return cls
    
    if cls: return AddPanels(cls, kwargs)
    return (lambda cls: AddPanels(cls, kwargs))

change_monitor = ChangeMonitor(update=False)

@addon.Operator(idname="object.batch_hide", options={'INTERNAL', 'REGISTER'}, label="Visibility", description="Restrict viewport visibility")
def Operator_Hide(self, context, event, idnames="", state=False):
    if event is not None:
        if event.shift: state = False # Shift -> force show
        elif event.ctrl: state = True # Ctrl -> force hide
    idnames = set(idnames.split(idnames_separator))
    bpy.ops.ed.undo_push(message="Batch Restrict Visibility")
    for obj in context.scene.objects:
        if obj.name in idnames: obj.hide = state
    return {'FINISHED'}

@addon.Operator(idname="object.batch_hide_select", options={'INTERNAL', 'REGISTER'}, label="Selection", description="Restrict viewport selection")
def Operator_Hide_Select(self, context, event, idnames="", state=False):
    if event is not None:
        if event.shift: state = False # Shift -> force show
        elif event.ctrl: state = True # Ctrl -> force hide
    idnames = set(idnames.split(idnames_separator))
    bpy.ops.ed.undo_push(message="Batch Restrict Selection")
    for obj in context.scene.objects:
        if obj.name in idnames: obj.hide_select = state
    return {'FINISHED'}

@addon.Operator(idname="object.batch_hide_render", options={'INTERNAL', 'REGISTER'}, label="Rendering", description="Restrict rendering")
def Operator_Hide_Render(self, context, event, idnames="", state=False):
    if event is not None:
        if event.shift: state = False # Shift -> force show
        elif event.ctrl: state = True # Ctrl -> force hide
    idnames = set(idnames.split(idnames_separator))
    bpy.ops.ed.undo_push(message="Batch Restrict Rendering")
    for obj in context.scene.objects:
        if obj.name in idnames: obj.hide_render = state
    return {'FINISHED'}

@addon.Operator(idname="object.batch_set_layers", options={'INTERNAL', 'REGISTER'}, label="Layers", description="Set layers")
class Operator_Set_Layers:
    idnames = "" | prop()
    layers = (False,)*20 | prop("Layers", "Layers")
    layers_same = (False,)*20 | prop()
    
    def invoke(self, context, event):
        idnames = set(self.idnames.split(idnames_separator))
        aggr = VectorAggregator(len(self.layers), 'BOOL', {"same", "mean"})
        for obj in context.scene.objects:
            if obj.name in idnames: aggr.add(obj.layers)
        self.layers = tuple(round_to_bool(state) for state in aggr.mean)
        self.layers_same = aggr.same
        wm = context.window_manager
        return wm.invoke_props_dialog(self)
    
    def execute(self, context):
        idnames = set(self.idnames.split(idnames_separator))
        bpy.ops.ed.undo_push(message="Batch Set Layers")
        for obj in context.scene.objects:
            if obj.name in idnames: obj.layers = self.layers
        return {'FINISHED'}
    
    def draw_row(self, layout, i_start):
        with layout.row(True):
            for i in range(i_start, i_start+5):
                same = self.layers_same[i]
                layout.row(True)(alert=not same).prop(self, "layers", index=i, text="", icon='BLANK1', toggle=True)
    
    def draw(self, context):
        layout = NestedLayout(self.layout)
        with layout.row():
            with layout.column(True):
                self.draw_row(layout, 0)
                self.draw_row(layout, 10)
            with layout.column(True):
                self.draw_row(layout, 5)
                self.draw_row(layout, 15)

@addon.Operator(idname="object.batch_parent_to_empty", options={'INTERNAL', 'REGISTER'}, label="Parent To Empty", description=
"Click: Parent To Empty (+Ctrl: place parent at 3D cursor)")
def Operator_Parent_To_Empty(self, context, event, idnames="", category_idnames=""):
    # ? options: at active obj, at cursor, at average, at center
    idnames = set(idnames.split(idnames_separator))
    objs_matrices = tuple((obj, obj.matrix_world.copy()) for obj in context.scene.objects if obj.name in idnames)
    
    bpy.ops.ed.undo_push(message="Batch Parent To Empty")
    
    parent_name = category_idnames.replace(idnames_separator, "+")
    
    if event and event.ctrl:
        parent_pos = Vector(context.scene.cursor_location)
    else:
        parent_pos = sum((m.translation.copy() for obj, m in objs_matrices), Vector()) * (1.0 / len(objs_matrices))
    
    old_empty_parents = set()
    for obj, m in objs_matrices:
        if obj.parent and (obj.parent.type == 'EMPTY'):
            if obj.parent.parent is None:
                old_empty_parents.add(obj.parent)
        obj.parent_type = 'OBJECT'
        obj.parent = None
        obj.parent_bone = ""
        obj.use_slow_parent = False
        obj.matrix_world = m
    
    for old_parent in old_empty_parents:
        if old_parent.children: continue
        context.scene.objects.unlink(old_parent)
        if old_parent.users == 0:
            bpy.data.objects.remove(old_parent)
    context.scene.update()
    
    # Create after deleting old parents to reduce the possibility of name conflicts
    new_parent = bpy.data.objects.new(parent_name, None)
    new_parent.location = parent_pos
    new_parent.show_name = True
    new_parent.show_x_ray = True
    context.scene.objects.link(new_parent)
    context.scene.update() # update to avoid glitches
    
    for obj, m in objs_matrices:
        obj.parent = new_parent
        obj.matrix_world = m
    context.scene.update()
    
    return {'FINISHED'}

def make_category(globalvars, idname_attr="name", **kwargs):
    Category_Name = globalvars["Category_Name"]
    CATEGORY_NAME = Category_Name.upper()
    category_name = Category_Name.lower()
    Category_Name_Plural = globalvars["Category_Name_Plural"]
    CATEGORY_NAME_PLURAL = Category_Name_Plural.upper()
    category_name_plural = Category_Name_Plural.lower()
    category_icon = globalvars["category_icon"]
    
    BatchOperations = globalvars["BatchOperations"]
    
    aggregate_attrs = kwargs.get("aggregate_attrs", [])
    _nongeneric_actions = kwargs.get("nongeneric_actions", [])
    quick_access_default = kwargs.get("quick_access_default", set())
    menu_options_extra = kwargs.get("menu_options_extra", [])
    options_mixin = kwargs.get("options_mixin", object)
    copy_paste_contexts = kwargs.get("copy_paste_contexts", ())
    is_ID = kwargs.get("is_ID", False) # is ID datablock
    
    @addon.Menu(idname="OBJECT_MT_batch_{}_add".format(category_name), description=
    "Add {}(s)".format(Category_Name))
    def Menu_Add(self, context):
        layout = NestedLayout(self.layout)
        if is_ID:
            #op = layout.operator("object.batch_{}_add".format(category_name), text="<Create new>", icon=category_icon)
            op = layout.operator("object.batch_{}_add".format(category_name), text="<Create new>", icon='NEW')
            op.create = True
        for item in CategoryPG.remaining_items:
            idname = item[0]
            name = item[1]
            icon_kw = BatchOperations.icon_kwargs(idname, False)
            op = layout.operator("object.batch_{}_add".format(category_name), text=name, **icon_kw)
            op.idnames = idname
    
    @addon.Operator(idname="view3d.pick_{}s".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Pick {}(s) from the object under mouse".format(Category_Name))
    class Operator_Pick(Pick_Base):
        @classmethod
        def poll(cls, context):
            return (context.mode == 'OBJECT')
        
        def obj_to_info(self, obj):
            txt = ", ".join(BatchOperations.iter_names(obj))
            return (txt or "<No {}>".format(category_name))
        
        def on_confirm(self, context, obj):
            category = get_category()
            options = get_options()
            bpy.ops.ed.undo_push(message="Pick {}s".format(Category_Name))
            BatchOperations.copy(obj)
            self.report({'INFO'}, "{}s copied".format(Category_Name))
            BatchOperations.paste(options.iterate_objects(context), options.paste_mode)
            category.tag_refresh()
    
    # NOTE: only when 'REGISTER' is in bl_options and {'FINISHED'} is returned,
    # the operator will be recorded in wm.operators and info reports
    
    @addon.Operator(idname="object.batch_{}_copy".format(category_name), options={'INTERNAL'}, description=
    "Click: Copy")
    def Operator_Copy(self, context, event):
        if not context.object: return
        BatchOperations.copy(context.object, CategoryPG.excluded)
        self.report({'INFO'}, "{}s copied".format(Category_Name))
    
    @addon.Operator(idname="object.batch_{}_paste".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Click: Paste (+Ctrl: Replace; +Shift: Add; +Alt: Filter)")
    def Operator_Paste(self, context, event):
        category = get_category()
        options = get_options()
        bpy.ops.ed.undo_push(message="Batch Paste {}s".format(Category_Name))
        paste_mode = options.paste_mode
        if event is not None:
            if event.shift: paste_mode = 'OR'
            elif event.ctrl: paste_mode = 'SET'
            elif event.alt: paste_mode = 'AND'
        BatchOperations.paste(options.iterate_objects(context), paste_mode)
        category.tag_refresh()
        return {'FINISHED'}
    
    @addon.Operator(idname="object.batch_{}_add".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Click: Add")
    def Operator_Add(self, context, event, idnames="", create=False):
        category = get_category()
        options = get_options()
        bpy.ops.ed.undo_push(message="Batch Add {}s".format(Category_Name))
        if is_ID and create: idnames = BatchOperations.new(Category_Name)
        BatchOperations.add(options.iterate_objects(context), idnames)
        category.tag_refresh()
        return {'FINISHED'}
    
    if is_ID:
        @addon.Operator(idname="object.batch_{}_replace".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
        "Click: Replace this {0} with another (+Ctrl: globally); Alt+Click: Replace {0}(s) with this one (+Ctrl: globally; +Shift: ensure)".format(category_name))
        def Operator_Replace(self, context, event, idnames="", index=0, title=""):
            category = get_category()
            options = get_options()
            if event.alt:
                if index > 0: # not applicable to "All"
                    globally = event.ctrl or (options.search_in == 'FILE')
                    bpy.ops.ed.undo_push(message="Batch Replace {}s".format(Category_Name))
                    BatchOperations.replace(options.iterate_objects(context, globally), None, idnames, globally, purge=globally)
                    if event.shift: BatchOperations.ensure(context.object, options.iterate_objects(context, globally), idnames)
                    category.tag_refresh()
                    return {'FINISHED'}
            else:
                globally = event.ctrl
                def draw_popup_menu(self, context):
                    layout = NestedLayout(self.layout)
                    for item in BatchOperations.enum_all():
                        idname = item[0]
                        name = item[1]
                        op = layout.operator("object.batch_{}_replace_reverse".format(category_name), text=name, icon=category_icon)
                        op.src_idnames = idnames
                        op.dst_idname = idname
                        op.globally = globally
                context.window_manager.popup_menu(draw_popup_menu, title="Replace {} with".format(title), icon='ARROW_LEFTRIGHT')
        
        @addon.Operator(idname="object.batch_{}_replace_reverse".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
        "Click: Replace this {0} with another (+Ctrl: globally)".format(category_name))
        def Operator_Replace_Reverse(self, context, event, src_idnames="", dst_idname="", globally=False):
            category = get_category()
            options = get_options()
            if event is not None: globally |= event.ctrl # ? maybe XOR?
            globally |= (options.search_in == 'FILE')
            bpy.ops.ed.undo_push(message="Batch Replace {}s".format(Category_Name))
            BatchOperations.replace(options.iterate_objects(context, globally), src_idnames, dst_idname, globally, purge=globally)
            category.tag_refresh()
            return {'FINISHED'}
    
    @addon.Operator(idname="object.batch_{}_name".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Click: Select objects; Shift+Click: (De)select row; Ctrl+Click: Rename; Alt+Click: Ensure")
    def Operator_Name(self, context, event, idnames="", index=0, title=""):
        category = get_category()
        options = get_options()
        if event.ctrl:
            if CategoryPG.rename_id != index:
                if index == 0: # All -> aggregate
                    if len(category.items) > 2:
                        aggr = Aggregator('STRING', {'subseq', 'subseq_starts', 'subseq_ends'})
                        for i in range(1, len(category.items)):
                            aggr.add(category.items[i].name)
                        pattern = PatternRenamer.make(aggr.subseq, aggr.subseq_starts, aggr.subseq_ends)
                    else:
                        pattern = category.items[1].name
                else:
                    pattern = category.items[index].name
                CategoryPG.rename_id = -1 # disable side-effects
                CategoryPG.src_pattern = pattern
                category.rename = pattern
                CategoryPG.rename_id = index # side-effects are enabled now
        elif event.alt:
            bpy.ops.ed.undo_push(message="Batch Ensure {}s".format(Category_Name))
            BatchOperations.ensure(context.object, options.iterate_objects(context, event.ctrl), idnames)
        elif event.shift:
            category = get_category()
            CategoryPG.toggle_excluded(category.items[index].idname)
        else:
            bpy.ops.ed.undo_push(message="Batch Select {}s".format(Category_Name))
            BatchOperations.select(context.scene, idnames)
        category.tag_refresh()
        return {'FINISHED'}
    
    @addon.Operator(idname="object.batch_{}_remove".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Click: Remove (+Ctrl: globally); Alt+Click: Purge")
    def Operator_Remove(self, context, event, idnames="", index=0, title=""):
        category = get_category()
        options = get_options()
        if event.alt:
            bpy.ops.ed.undo_push(message="Purge {}s".format(Category_Name))
            BatchOperations.purge(True, idnames)
        else:
            bpy.ops.ed.undo_push(message="Batch Remove {}s".format(Category_Name))
            BatchOperations.remove(options.iterate_objects(context, event.ctrl), idnames, (options.search_in == 'FILE'))
        category.tag_refresh()
        return {'FINISHED'}
    
    @addon.PropertyGroup
    class CategoryOptionsPG(options_mixin):
        def update_synchronized(self, context):
            pass
        synchronized = False | prop("Synchronized", "Synchronized", update=update_synchronized)
        
        def update_autorefresh(self, context):
            pass
        autorefresh = True | prop("Auto-refresh", update=update_autorefresh)
        
        def update(self, context):
            category = get_category()
            category.tag_refresh()
        
        paste_mode_icons = {'SET':'ROTACTIVE', 'OR':'ROTATECOLLECTION', 'AND':'ROTATECENTER'}
        paste_mode = 'SET' | prop("Paste mode", update=update, items=[
            ('SET', "Replace", "Replace objects' {}(s) with the copied ones".format(category_name), 'ROTACTIVE'),
            ('OR', "Add", "Add copied {}(s) to objects".format(category_name), 'ROTATECOLLECTION'),
            ('AND', "Filter", "Remove objects' {}(s) that are not among the copied".format(category_name), 'ROTATECENTER'),
        ])
        
        search_in_icons = {'SELECTION':'RESTRICT_SELECT_OFF', 'VISIBLE':'RESTRICT_VIEW_OFF',
            'LAYER':'RENDERLAYERS', 'SCENE':'SCENE_DATA', 'FILE':'FILE_BLEND'}
        search_in = 'SELECTION' | prop("Filter", update=update, items=[
            ('SELECTION', "Selection", "Display {}(s) of the selection".format(category_name), 'RESTRICT_SELECT_OFF'),
            ('VISIBLE', "Visible", "Display {}(s) of the visible objects".format(category_name), 'RESTRICT_VIEW_OFF'),
            ('LAYER', "Layer", "Display {}(s) of the objects in the visible layers".format(category_name), 'RENDERLAYERS'),
            ('SCENE', "Scene", "Display {}(s) of the objects in the current scene".format(category_name), 'SCENE_DATA'),
            ('FILE', "File", "Display all {}(s) in this file".format(category_name), 'FILE_BLEND'),
        ])
        
        def iterate(self, context=None, globally=False):
            search_in = ('FILE' if globally else self.search_in)
            return BatchOperations.iterate(search_in, context)
        def iterate_objects(self, context=None, globally=False):
            search_in = ('FILE' if globally else self.search_in)
            return BatchOperations.iterate_objects(search_in, context)
    
    class AggregateInfo:
        idname_attr = None
        aggr_infos = {}
        
        def __init__(self, idname, name):
            self.idname = idname
            self.name = name
            self.count = 0
            self.aggrs = {}
            for name, params in self.aggr_infos.items():
                self.aggrs[name] = Aggregator(*params["init"])
        
        def fill_item(self, item):
            item.name = self.name
            item.idname = self.idname
            item.count = self.count
            for name, params in self.aggr_infos.items():
                self.fill_aggr(item, name, *params["fill"])
            item.user_editable = True
        
        def fill_aggr(self, item, name, query, convert=None):
            aggr = self.aggrs[name]
            value = getattr(aggr, query)
            if convert is not None: value = convert(value)
            setattr(item, name, value)
            item[name+":same"] = aggr.same
        
        @classmethod
        def collect_info(cls, items, count_users=False):
            infos = {}
            for item in items:
                cls.extract_info(infos, item, "", count_users=count_users)
                cls.extract_info(infos, item, count_users=count_users)
            return infos
        
        @classmethod
        def extract_info(cls, infos, item, idname=None, count_users=False):
            if idname is None: idname = getattr(item, cls.idname_attr)
            
            info = infos.get(idname)
            if info is None:
                name = (BatchOperations.clean_name(item) if idname else "")
                infos[idname] = info = cls(idname, name) # double assign
            
            if count_users:
                if not idname:
                    info.count += item.users # All
                else:
                    info.count = item.users
            else:
                info.count += 1
            
            for name in cls.aggr_infos:
                info.aggrs[name].add(getattr(item, name))
    
    @addon.PropertyGroup
    class CategoryItemPG:
        sort_id = 0 | prop()
        user_editable = False | prop()
        count = 0 | prop()
        idname = "" | prop()
    
    AggregateInfo.idname_attr = idname_attr
    
    def make_update(name):
        def update(self, context):
            if not self.user_editable: return
            category = get_category()
            options = get_options()
            message = self.bl_rna.properties[name].description
            value = getattr(self, name)
            bpy.ops.ed.undo_push(message=message)
            idnames = self.idname or category.all_idnames
            BatchOperations.set_attr(name, value, options.iterate_objects(context), idnames)
            category.tag_refresh()
        return update
    
    if is_ID:
        aggregate_attrs.append(("use_fake_user", dict(tooltip="Keep this datablock even if it has no users")))
        _nongeneric_actions.append(("aggregate_toggle", dict(property="use_fake_user", text="Extra fake user", icons=('PINNED', 'UNPINNED'))))
        quick_access_default.add("use_fake_user")
        _nongeneric_actions.append(("operator", dict(operator="object.batch_{}_replace".format(category_name), text="Replace", icon='ARROW_LEFTRIGHT')))
        quick_access_default.add("object.batch_{}_replace".format(category_name))
    
    quick_access_items = []
    nongeneric_actions = []
    nongeneric_actions_no_text = []
    
    for cmd, cmd_kwargs in _nongeneric_actions:
        if cmd == "operator":
            action_idname = cmd_kwargs.get("operator")
        else:
            action_idname = cmd_kwargs.get("property")
        action_name = cmd_kwargs.get("text", action_idname)
        quick_access_items.append((action_idname, action_name, action_name))
        
        if cmd == "aggregate_toggle":
            icons = cmd_kwargs.get("icons")
            if icons is None: icons = ('CHECKBOX_HLT', 'CHECKBOX_DEHLT')
            elif isinstance(icons, str): icons = (icons, icons)
            cmd_kwargs["icons"] = icons
        
        nongeneric_actions.append((cmd, cmd_kwargs, action_idname))
        
        cmd_kwargs = dict(cmd_kwargs)
        cmd_kwargs["text"] = ""
        nongeneric_actions_no_text.append((cmd, cmd_kwargs, action_idname))
    
    for name, params in aggregate_attrs:
        prop_kwargs = params.get("prop")
        if prop_kwargs is None: prop_kwargs = {}
        if "default" not in prop_kwargs:
            prop_kwargs["default"] = False
        if "tooltip" in params:
            prop_kwargs["description"] = params["tooltip"]
        if "update" not in prop_kwargs:
            prop_kwargs["update"] = params.get("update") or make_update(name)
        setattr(CategoryItemPG, name, None | prop(**prop_kwargs))
        
        aggr = params.get("aggr")
        if aggr is None: aggr = dict(init=('BOOL', {"same", "mean"}), fill=("mean", round_to_bool))
        AggregateInfo.aggr_infos[name] = aggr
    
    CategoryOptionsPG.quick_access = quick_access_default | prop("Quick access", "Quick access", items=quick_access_items)
    
    def aggregate_toggle(layout, item, property, icons, text=""):
        icon = (icons[0] if getattr(item, property) else icons[1])
        with layout.row(True)(alert=not item[property+":same"]):
            layout.prop(item, property, icon=icon, text=text, toggle=True)
    
    @addon.PropertyGroup
    class CategoryPG:
        prev_idnames = set()
        excluded = set()
        
        def update_rename(self, context):
            if CategoryPG.rename_id < 0: return
            category = get_category()
            options = get_options()
            # The bad thing is, undo seems to not be pushed from an update callback
            bpy.ops.ed.undo_push(message="Rename {}".format(category_name))
            idnames = category.items[CategoryPG.rename_id].idname or category.all_idnames
            BatchOperations.set_attr("name", self.rename, options.iterate(context), idnames, src_pattern=CategoryPG.src_pattern)
            CategoryPG.rename_id = -1 # Auto switch off
            category.tag_refresh()
        
        rename_id = -1
        src_pattern = ""
        rename = "" | prop("Rename", "", update=update_rename)
        
        was_drawn = False | prop()
        next_refresh_time = -1.0 | prop()
        
        needs_refresh = True | prop()
        def tag_refresh(self):
            self.needs_refresh = True
            tag_redraw()
        
        all_idnames = property(lambda self: idnames_separator.join(
            item.idname for item in self.items
            if item.idname and not CategoryPG.is_excluded(item.idname)))
        
        items = [CategoryItemPG] | prop()
        
        remaining_items = []
        
        @classmethod
        def is_excluded(cls, idname):
            return idname in cls.excluded
        @classmethod
        def set_excluded(cls, idname, value):
            if value:
                cls.excluded.add(idname)
            else:
                cls.excluded.discard(idname)
        @classmethod
        def toggle_excluded(cls, idname):
            if idname in cls.excluded:
                cls.excluded.discard(idname)
            else:
                cls.excluded.add(idname)
        
        def refresh(self, context, needs_refresh=False):
            options = get_options()
            needs_refresh |= self.needs_refresh
            needs_refresh |= options.autorefresh and (time.clock() > self.next_refresh_time)
            if not needs_refresh: return
            self.next_refresh_time = time.clock() + addon.preferences.refresh_interval
            
            cls = self.__class__
            
            processing_time = time.clock()
            
            infos = AggregateInfo.collect_info(options.iterate(context), is_ID and (options.search_in == 'FILE'))
            
            curr_idnames = set(infos.keys())
            if curr_idnames != cls.prev_idnames:
                # remember excluded state while idnames are the same
                cls.excluded.clear()
                CategoryPG.rename_id = -1
            cls.prev_idnames = curr_idnames
            
            cls.remaining_items = [enum_item
                for enum_item in BatchOperations.enum_all()
                if enum_item[0] not in curr_idnames]
            cls.remaining_items.sort(key=lambda item:item[1])
            
            self.items.clear()
            for i, key in enumerate(sorted(infos.keys())):
                item = self.items.add()
                item.sort_id = i
                infos[key].fill_item(item)
            
            processing_time = time.clock() - processing_time
            # Disable autorefresh if it takes too much time
            #if processing_time > 0.05: options.autorefresh = False
            
            self.needs_refresh = False
        
        def draw(self, layout):
            self.was_drawn = True
            self.refresh(bpy.context)
            
            if not self.items: return
            
            options = get_options()
            
            all_idnames = self.all_idnames
            
            with layout.column(True):
                for item in self.items:
                    with layout.row(True)(active=(item.idname not in CategoryPG.excluded)):
                        title = item.name or "(All)"
                        icon_kw = BatchOperations.icon_kwargs(item.idname)
                        icon_novalue = BatchOperations.icon_kwargs(item.idname, False)["icon"]
                        
                        #layout.menu("VIEW3D_MT_batch_{}_extras".format(category_name_plural), text="", icon='DOTSDOWN')
                        op = layout.operator("object.batch_{}_extras".format(category_name), text="", icon='DOTSDOWN')
                        op.idnames = item.idname or all_idnames
                        op.index = item.sort_id
                        op.title = title
                        
                        for cmd, cmd_kwargs, action_idname in nongeneric_actions_no_text:
                            if action_idname not in options.quick_access: continue
                            if cmd == "aggregate_toggle":
                                aggregate_toggle(layout, item, **cmd_kwargs)
                            elif cmd == "operator":
                                if "icon" in cmd_kwargs:
                                    op = layout.operator(**cmd_kwargs)
                                else:
                                    op = layout.operator(icon=icon_novalue, **cmd_kwargs)
                                op.idnames = item.idname or all_idnames
                                op.index = item.sort_id
                                op.title = title
                        
                        if CategoryPG.rename_id == item.sort_id:
                            layout.prop(self, "rename", text="")
                        else:
                            #icon_kw = BatchOperations.icon_kwargs(idname, False)
                            text = "{} ({})".format(title, item.count)
                            op = layout.operator("object.batch_{}_name".format(category_name), text=text)
                            op.idnames = item.idname or all_idnames
                            op.index = item.sort_id
                        
                        op = layout.operator("object.batch_{}_remove".format(category_name), text="", icon='X')
                        op.idnames = item.idname or all_idnames
                        op.index = item.sort_id
    
    CategoryPG.Category_Name = Category_Name
    CategoryPG.CATEGORY_NAME = CATEGORY_NAME
    CategoryPG.category_name = category_name
    CategoryPG.Category_Name_Plural = Category_Name_Plural
    CategoryPG.CATEGORY_NAME_PLURAL = CATEGORY_NAME_PLURAL
    CategoryPG.category_name_plural = category_name_plural
    CategoryPG.category_icon = category_icon
    
    @addon.Operator(idname="object.batch_{}_extras".format(category_name), options={'INTERNAL'}, description="Extras")
    def Operator_Extras(self, context, event, idnames="", index=0, title=""):
        category = get_category()
        options = get_options()
        
        item = category.items[index]
        icon_novalue = BatchOperations.icon_kwargs(item.idname, False)["icon"]
        
        search_in = options.search_in
        if search_in == 'FILE': search_in = 'SCENE' # shouldn't affect other scenes here
        
        #related_objs_scene = tuple(BatchOperations.find_objects(idnames, 'SCENE'))
        #related_objs_idnames_scene = idnames_separator.join(obj.name for obj in related_objs_scene)
        
        related_objs = tuple(BatchOperations.find_objects(idnames, search_in))
        related_objs_idnames = idnames_separator.join(obj.name for obj in related_objs)
        
        aggr_hide = Aggregator('BOOL', {"min", "max"})
        aggr_hide_select = Aggregator('BOOL', {"min", "max"})
        aggr_hide_render = Aggregator('BOOL', {"min", "max"})
        for obj in related_objs:
            aggr_hide.add(obj.hide)
            aggr_hide_select.add(obj.hide_select)
            aggr_hide_render.add(obj.hide_render)
        
        # The user is probably more interested in "is there something visible at all?"
        is_hide = bool(aggr_hide.min)
        is_hide_select = bool(aggr_hide_select.min)
        is_hide_render = bool(aggr_hide_render.min)
        ('CHECKBOX_HLT', 'CHECKBOX_DEHLT')
        
        def draw_popup_menu(self, context):
            layout = NestedLayout(self.layout)
            
            for cmd, cmd_kwargs, action_idname in nongeneric_actions:
                if cmd == "aggregate_toggle":
                    aggregate_toggle(layout, item, **cmd_kwargs)
                elif cmd == "operator":
                    if "icon" in cmd_kwargs:
                        op = layout.operator(**cmd_kwargs)
                    else:
                        op = layout.operator(icon=icon_novalue, **cmd_kwargs)
                    op.idnames = idnames
                    op.index = item.sort_id
                    op.title = title
            
            icon = ('RESTRICT_VIEW_ON' if is_hide else 'RESTRICT_VIEW_OFF')
            op = layout.operator("object.batch_hide", icon=icon)
            op.idnames = related_objs_idnames
            op.state = not is_hide
            
            icon = ('RESTRICT_SELECT_ON' if is_hide_select else 'RESTRICT_SELECT_OFF')
            op = layout.operator("object.batch_hide_select", icon=icon)
            op.idnames = related_objs_idnames
            op.state = not is_hide_select
            
            icon = ('RESTRICT_RENDER_ON' if is_hide_render else 'RESTRICT_RENDER_OFF')
            op = layout.operator("object.batch_hide_render", icon=icon)
            op.idnames = related_objs_idnames
            op.state = not is_hide_render
            
            op = layout.operator("object.batch_set_layers", icon='RENDERLAYERS')
            op.idnames = related_objs_idnames
            
            op = layout.operator("object.batch_parent_to_empty", icon='OUTLINER_OB_EMPTY') # or 'OOPS' ?
            op.idnames = related_objs_idnames
            op.category_idnames = idnames
        
        context.window_manager.popup_menu(draw_popup_menu, title="{} extras".format(title), icon='DOTSDOWN')
    
    @addon.Menu(idname="VIEW3D_MT_batch_{}_options_paste_mode".format(category_name_plural), label="Paste mode", description="Paste mode")
    def Menu_PasteMode(self, context):
        layout = NestedLayout(self.layout)
        options = get_options()
        layout.props_enum(options, "paste_mode")
    
    @addon.Menu(idname="VIEW3D_MT_batch_{}_options_search_in".format(category_name_plural), label="Filter", description="Filter")
    def Menu_SearchIn(self, context):
        layout = NestedLayout(self.layout)
        options = get_options()
        layout.props_enum(options, "search_in")
    
    if is_ID:
        @addon.Operator(idname="object.batch_{}_purge_unused".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
        "Click: Purge unused (+Ctrl: even those with use_fake_users)", label="Purge unused")
        def Operator_Purge_Unused(self, context, event):
            category = get_category()
            options = get_options()
            bpy.ops.ed.undo_push(message="Purge Unused {}".format(Category_Name_Plural))
            BatchOperations.purge(event.ctrl)
            category.tag_refresh()
            return {'FINISHED'}
        menu_options_extra.append(("operator", dict(operator="object.batch_{}_purge_unused".format(category_name), icon='GHOST_DISABLED')))
        
        @addon.Operator(idname="object.batch_{}_merge_identical".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
        "Click: Merge identical", label="Merge identical")
        def Operator_Merge_Identical(self, context, event):
            category = get_category()
            options = get_options()
            bpy.ops.ed.undo_push(message="Merge Identical {}".format(Category_Name_Plural))
            BatchOperations.merge_identical()
            category.tag_refresh()
            return {'FINISHED'}
        menu_options_extra.append(("operator", dict(operator="object.batch_{}_merge_identical".format(category_name), icon='AUTOMERGE_ON')))
    
    @addon.Menu(idname="VIEW3D_MT_batch_{}_options".format(category_name_plural), label="Options", description="Options")
    def Menu_Options(self, context):
        layout = NestedLayout(self.layout)
        options = get_options()
        layout.prop(options, "synchronized")
        layout.menu("VIEW3D_MT_batch_{}_options_paste_mode".format(category_name_plural), icon='PASTEDOWN')
        layout.menu("VIEW3D_MT_batch_{}_options_search_in".format(category_name_plural), icon='VIEWZOOM')
        for cmd, cmd_kwargs in menu_options_extra:
            getattr(layout, cmd)(**cmd_kwargs)
    
    @addon.Operator(idname="object.batch_{}_refresh".format(category_name), options={'INTERNAL', 'REGISTER'}, description=
    "Click: Force refresh; Ctrl+Click: Toggle auto-refresh")
    def Operator_Refresh(self, context, event):
        category = get_category()
        options = get_options()
        if event.ctrl:
            options.autorefresh = not options.autorefresh
        else:
            category.refresh(context, True)
        return {'FINISHED'}
    
    @LeftRightPanel(idname="VIEW3D_PT_batch_{}".format(category_name_plural), context="objectmode", space_type='VIEW_3D', category="Batch", label="Batch {}s".format(Category_Name))
    class Panel_Category:
        def draw_header(self, context):
            layout = NestedLayout(self.layout)
            category = get_category()
            options = get_options()
            with layout.row(True):
                icon = CategoryOptionsPG.search_in_icons[options.search_in]
                layout.prop_menu_enum(options, "search_in", text="", icon=icon)
                icon = CategoryOptionsPG.paste_mode_icons[options.paste_mode]
                layout.prop_menu_enum(options, "paste_mode", text="", icon=icon)
        
        def draw(self, context):
            layout = NestedLayout(self.layout)
            category = get_category()
            options = get_options()
            
            with layout.row():
                with layout.row(True):
                    layout.menu("OBJECT_MT_batch_{}_add".format(category_name), icon='ZOOMIN', text="")
                    layout.operator("view3d.pick_{}".format(category_name_plural), icon='EYEDROPPER', text="")
                    layout.operator("object.batch_{}_copy".format(category_name), icon='COPYDOWN', text="")
                    layout.operator("object.batch_{}_paste".format(category_name), icon='PASTEDOWN', text="")
                
                icon = ('PREVIEW_RANGE' if options.autorefresh else 'FILE_REFRESH')
                layout.operator("object.batch_{}_refresh".format(category_name), icon=icon, text="")
                
                icon = ('SCRIPTPLUGINS' if options.synchronized else 'SCRIPTWIN')
                layout.menu("VIEW3D_MT_batch_{}_options".format(category_name_plural), icon=icon, text="")
            
            category.draw(layout)
    
    setattr(addon.External, category_name_plural, CategoryPG | -prop())
    get_category = eval("lambda: addon.external.{}".format(category_name_plural))
    
    setattr(addon.Preferences, category_name_plural, CategoryOptionsPG | prop())
    get_options = eval("lambda: addon.preferences.{}".format(category_name_plural))
    
    prefs_categories = getattr(addon.Preferences, "categories", None)
    if prefs_categories is None:
        prefs_categories = []
        addon.Preferences.categories = prefs_categories
    prefs_categories.append(CategoryPG)
    
    prefs_copy_paste_contexts = getattr(addon.Preferences, "copy_paste_contexts", None)
    if prefs_copy_paste_contexts is None:
        prefs_copy_paste_contexts = {}
        addon.Preferences.copy_paste_contexts = prefs_copy_paste_contexts
    prefs_copy_paste_contexts.update((context, CategoryPG) for context in copy_paste_contexts)
    
    globalvars.update(locals())
