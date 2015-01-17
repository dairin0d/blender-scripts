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
from {0}dairin0d.utils_accumulation import Aggregator, aggregated
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

from .batch_common import (
    copyattrs, attrs_to_dict, dict_to_attrs, PatternRenamer,
    Pick_Base, LeftRightPanel, make_category,
    round_to_bool, is_visible, has_common_layers, idnames_separator
)

addon = AddonManager()

#============================================================================#
Category_Name = "Group"
CATEGORY_NAME = Category_Name.upper()
category_name = Category_Name.lower()
Category_Name_Plural = "Groups"
CATEGORY_NAME_PLURAL = Category_Name_Plural.upper()
category_name_plural = Category_Name_Plural.lower()
category_icon = 'GROUP'

Group = bpy.types.Group

class BatchOperations:
    clipbuffer = None
    
    @classmethod
    def to_group(cls, group):
        if isinstance(group, Group): return group
        return bpy.data.groups.get(group)
    
    @classmethod
    def add_group_to_obj(cls, obj, idname):
        group = cls.to_group(idname)
        if obj.name not in group.objects: group.objects.link(obj)
    
    @classmethod
    def clear_obj_groups(cls, obj, idnames=None, check_in=True):
        for group in bpy.data.groups:
            if (idnames is None) or ((group.name in idnames) == check_in):
                if obj.name in group.objects: group.objects.unlink(obj)
    
    @classmethod
    def clean_name(cls, group):
        return group.name
    
    @classmethod
    def iter_names(cls, obj):
        for group in bpy.data.groups:
            if obj.name in group.objects: yield group.name
    
    @classmethod
    def enum_all(cls):
        for group in bpy.data.groups:
            yield (group.name, group.name, group.name)
    
    @classmethod
    def icon_kwargs(cls, idname, use_value=True):
        return {"icon": category_icon}
    
    @classmethod
    def iterate(cls, search_in, context=None):
        if search_in != 'FILE':
            for obj in cls.iterate_objects(search_in, context):
                for group in bpy.data.groups:
                    if obj.name in group.objects: yield group
        else:
            yield from bpy.data.groups
    
    @classmethod
    def iterate_objects(cls, search_in, context=None):
        if context is None: context = bpy.context
        scene = context.scene
        if search_in == 'SELECTION':
            for obj in context.selected_objects:
                yield obj
        elif search_in == 'VISIBLE':
            for obj in scene.objects:
                if is_visible(obj, scene):
                    yield obj
        elif search_in == 'LAYER':
            for obj in scene.objects:
                if has_common_layers(obj, scene):
                    yield obj
        elif search_in == 'SCENE':
            for obj in scene.objects:
                yield obj
        elif search_in == 'FILE':
            for obj in bpy.data.objects:
                yield obj
    
    @classmethod
    def split_idnames(cls, idnames):
        if idnames is None: return None
        if not isinstance(idnames, str): return set(idnames)
        return set(idnames.split(idnames_separator))
    
    @classmethod
    def new(cls, idname):
        group = bpy.data.groups.new(idname)
        return group.name
    
    @classmethod
    def set_attr(cls, name, value, objects, idnames, **kwargs):
        idnames = cls.split_idnames(idnames)
        
        if name == "use_fake_user":
            obj = None
            
            for idname in idnames:
                group = cls.to_group(idname)
                if not group: continue
                
                if value:
                    # can't set use_fake_user if 0 users
                    if group.users == 0:
                        if obj is None: obj = bpy.data.objects.new("TmpObj", None)
                        group.objects.link(obj)
                else:
                    # can't unset use_fake_user if fake is the only user
                    if group.users == 1:
                        if obj is None: obj = bpy.data.objects.new("TmpObj", None)
                        group.objects.link(obj)
                
                group.use_fake_user = value
                
                if obj: group.objects.unlink(obj)
            
            if obj: bpy.data.objects.remove(obj)
        else:
            use_kwargs = False
            
            _setattr = setattr
            if isinstance(value, str):
                if PatternRenamer.is_pattern(value):
                    _setattr = PatternRenamer.apply_to_attr
                    use_kwargs = True
            
            if not use_kwargs: kwargs = {}
            
            for obj in objects:
                if isinstance(obj, Group):
                    if obj.name in idnames:
                        _setattr(obj, name, value, **kwargs)
                else:
                    for group in bpy.data.groups:
                        if obj.name not in group.objects: continue
                        if group.name in idnames:
                            _setattr(ms.group, name, value, **kwargs)
    
    @classmethod
    def clear(cls, objects):
        for obj in objects:
            cls.clear_obj_groups(obj)
    
    @classmethod
    def add(cls, objects, idnames):
        print("adding %s" % idnames)
        idnames = cls.split_idnames(idnames)
        for obj in objects:
            for idname in idnames:
                cls.add_group_to_obj(obj, idname)
    
    @classmethod
    def ensure(cls, active_obj, objects, idnames):
        idnames = cls.split_idnames(idnames)
        for obj in objects:
            for idname in idnames.difference(cls.iter_names(obj)):
                cls.add_group_to_obj(obj, idname)
    
    @classmethod
    def remove(cls, objects, idnames, from_file=False):
        cls.replace(objects, idnames, "", from_file)
    
    @classmethod
    def replace(cls, objects, src_idnames, dst_idname, from_file=False, purge=False):
        idnames = cls.split_idnames(src_idnames)
        dst_group = cls.to_group(dst_idname)
        
        replaced_idnames = set()
        
        if from_file: objects = bpy.data.objects
        
        for obj in objects:
            for group in bpy.data.groups:
                if obj.name not in group.objects: continue
                if (idnames is None) or (group.name in idnames):
                    replaced_idnames.add(group.name)
                    group.objects.unlink(obj)
                    if dst_group and (obj.name not in dst_group.objects):
                        dst_group.objects.link(obj)
        
        replaced_idnames.discard(dst_idname)
        
        if purge and replaced_idnames:
            cls.set_attr("use_fake_user", False, None, replaced_idnames)
            for group in tuple(bpy.data.groups):
                if group.name in replaced_idnames:
                    bpy.data.groups.remove(group)
    
    @classmethod
    def find_objects(cls, idnames, search_in, context=None):
        idnames = cls.split_idnames(idnames)
        groups = [group for group in bpy.data.groups if group.name in idnames]
        for obj in cls.iterate_objects(search_in, context):
            if any((obj.name in group.objects) for group in groups):
                yield obj
    
    @classmethod
    def select(cls, scene, idnames):
        idnames = cls.split_idnames(idnames)
        groups = [group for group in bpy.data.groups if group.name in idnames]
        for obj in scene.objects:
            obj.select = any((obj.name in group.objects) for group in groups)
    
    @classmethod
    def purge(cls, even_with_fake_users, idnames=None):
        if idnames is None:
            if even_with_fake_users:
                fake_idnames = (group.name for group in bpy.data.groups if group.use_fake_user and (group.users == 1))
                cls.set_attr("use_fake_user", False, None, fake_idnames)
            for group in tuple(bpy.data.groups):
                if group.users > 0: continue
                bpy.data.groups.remove(group)
        else:
            cls.remove(None, idnames, True)
            cls.set_attr("use_fake_user", False, None, idnames)
            idnames = cls.split_idnames(idnames)
            for group in tuple(bpy.data.groups):
                if group.name in idnames:
                    bpy.data.groups.remove(group)
    
    @classmethod
    def copy(cls, active_obj, exclude=()):
        if not active_obj:
            cls.clipbuffer = []
        else:
            cls.clipbuffer = [group.name for group in bpy.data.groups
                if (group.name not in exclude) and (active_obj.name in group.objects)]
    
    @classmethod
    def paste(cls, objects, paste_mode):
        idnames = cls.clipbuffer
        if idnames is None: return
        if paste_mode != 'AND':
            for obj in objects:
                if paste_mode == 'SET': cls.clear_obj_groups(obj)
                for idname in idnames:
                    cls.add_group_to_obj(obj, idname)
        else:
            for obj in objects:
                cls.clear_obj_groups(obj, idnames, False)
    
    @classmethod
    def merge_identical(cls):
        unique = set(bpy.data.groups)
        identical = []
        ignore = {"name"}
        
        for item in bpy.data.groups:
            duplicates = None
            unique.discard(item)
            
            for item2 in unique:
                if BlRna.compare(item, item2, ignore=ignore):
                    if duplicates is None: duplicates = {item}
                    duplicates.add(item2)
            
            if duplicates is not None:
                identical.append(duplicates)
                unique.difference_update(duplicates)
        
        for duplicates in identical:
            # find best candidate for preservation
            best, best_users, best_len = None, 0, 0
            for item in duplicates:
                if item.users >= best_users:
                    is_better = (item.users > best_users)
                    is_better |= (best_len <= 0)
                    is_better |= (len(item.name) < best_len)
                    if is_better:
                        best, best_users, best_len = item, item.users, len(item.name)
            duplicates.discard(best)
            src_idnames = idnames_separator.join(item.name for item in duplicates)
            dst_idname = best.name
            cls.replace(None, src_idnames, dst_idname, from_file=True, purge=True)

#============================================================================#

make_category(globals(), is_ID=True)
