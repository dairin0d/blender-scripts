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

"""
It's actually the data (mesh, curve, surface, metaball, text) that dictates the number of materials.
The data has its own list of materials, but they can be overridden on object level
by changing the corresponding slot's link type to 'OBJECT'.

* options synchronization
* in edit mode, 'SELECTION' mode should be interpreted as mesh/etc. selection?
* [DONE] rename (for All: rename listed materials by some pattern, e.g. common name + id, or the corresponding data/object name)
* [DONE] replace
* merge identical?
* make single-user copies? (this is probably useless)
* Option "Affect data": can modify data materials or switch slot.link to OBJECT
    * if object's data has only 1 user, we can directly modify the data anyway
* Option "Reuse slots": when adding material, use unoccupied slots first, or always creating new ones
"""

#============================================================================#
Category_Name = "Material"
CATEGORY_NAME = Category_Name.upper()
category_name = Category_Name.lower()
Category_Name_Plural = "Materials"
CATEGORY_NAME_PLURAL = Category_Name_Plural.upper()
category_name_plural = Category_Name_Plural.lower()
category_icon = 'MATERIAL'

Material = bpy.types.Material
MaterialSlot = bpy.types.MaterialSlot

class BatchOperations:
    clipbuffer = None
    
    @classmethod
    def to_material(cls, material):
        if isinstance(material, Material): return material
        if isinstance(material, MaterialSlot): return material.material
        return bpy.data.materials.get(material)
    
    @classmethod
    def add_material_to_obj(cls, obj, idname):
        material = cls.to_material(idname)
        for ms in obj.material_slots:
            if not ms.material:
                ms.link = 'OBJECT'
                ms.material = material
                break
        else: # no free slots found
            obj.data.materials.append(None)
            ms = obj.material_slots[len(obj.material_slots)-1]
            ms.link = 'OBJECT'
            ms.material = material
    
    @classmethod
    def clear_obj_materials(cls, obj, idnames=None, check_in=True):
        for ms in obj.material_slots:
            if (idnames is None) or ((ms.name in idnames) == check_in):
                ms.link = 'OBJECT'
                ms.material = None
    
    @classmethod
    def clean_name(cls, mat):
        return mat.name
    
    @classmethod
    def iter_names(cls, obj):
        for ms in obj.material_slots:
            if not ms.material: continue
            yield ms.name
    
    @classmethod
    def enum_all(cls):
        for mat in bpy.data.materials:
            yield (mat.name, mat.name, mat.name)
    
    @classmethod
    def icon_kwargs(cls, idname, use_value=True):
        # Currently only 2 layout commands support icon_value parameter
        if (not idname) or (not use_value): return {"icon": category_icon}
        try:
            return {"icon_value": bpy.types.UILayout.icon(bpy.data.materials.get(idname))}
        except:
            return {"icon": category_icon}
    
    @classmethod
    def iterate(cls, search_in, context=None):
        if search_in != 'FILE':
            for obj in cls.iterate_objects(search_in, context):
                for ms in obj.material_slots:
                    if ms.material: yield ms.material
        else:
            yield from bpy.data.materials
    
    @classmethod
    def iterate_objects(cls, search_in, context=None):
        if context is None: context = bpy.context
        obj_types = BlEnums.object_types_geometry
        scene = context.scene
        if search_in == 'SELECTION':
            for obj in context.selected_objects:
                if (obj.type in obj_types):
                    yield obj
        elif search_in == 'VISIBLE':
            for obj in scene.objects:
                if (obj.type in obj_types) and is_visible(obj, scene):
                    yield obj
        elif search_in == 'LAYER':
            for obj in scene.objects:
                if (obj.type in obj_types) and has_common_layers(obj, scene):
                    yield obj
        elif search_in == 'SCENE':
            for obj in scene.objects:
                if (obj.type in obj_types):
                    yield obj
        elif search_in == 'FILE':
            for obj in bpy.data.objects:
                if (obj.type in obj_types):
                    yield obj
    
    @classmethod
    def split_idnames(cls, idnames):
        if idnames is None: return None
        if not isinstance(idnames, str): return set(idnames)
        return set(idnames.split(idnames_separator))
    
    @classmethod
    def new(cls, idname):
        mat = bpy.data.materials.new(idname)
        return mat.name
    
    @classmethod
    def set_attr(cls, name, value, objects, idnames, **kwargs):
        idnames = cls.split_idnames(idnames)
        
        if name == "use_fake_user":
            mesh = None
            
            for idname in idnames:
                mat = cls.to_material(idname)
                if not mat: continue
                
                if value:
                    # can't set use_fake_user if 0 users
                    if mat.users == 0:
                        if mesh is None: mesh = bpy.data.meshes.new("TmpMesh")
                        mesh.materials.append(mat)
                else:
                    # can't unset use_fake_user if fake is the only user
                    if mat.users == 1:
                        if mesh is None: mesh = bpy.data.meshes.new("TmpMesh")
                        mesh.materials.append(mat)
                
                mat.use_fake_user = value
                
                if mesh: mesh.materials.pop(0)
            
            if mesh: bpy.data.meshes.remove(mesh)
        else:
            use_kwargs = False
            
            _setattr = setattr
            if isinstance(value, str):
                if PatternRenamer.is_pattern(value):
                    _setattr = PatternRenamer.apply_to_attr
                    use_kwargs = True
            
            if not use_kwargs: kwargs = {}
            
            for obj in objects:
                if isinstance(obj, Material):
                    if obj.name in idnames:
                        _setattr(obj, name, value, **kwargs)
                else:
                    for ms in obj.material_slots:
                        if not ms.material: continue
                        if ms.name in idnames:
                            _setattr(ms.material, name, value, **kwargs)
    
    @classmethod
    def clear(cls, objects):
        for obj in objects:
            cls.clear_obj_materials(obj)
    
    @classmethod
    def add(cls, objects, idnames):
        idnames = cls.split_idnames(idnames)
        for obj in objects:
            for idname in idnames:
                cls.add_material_to_obj(obj, idname)
    
    @classmethod
    def ensure(cls, active_obj, objects, idnames):
        idnames = cls.split_idnames(idnames)
        for obj in objects:
            for idname in idnames.difference(cls.iter_names(obj)):
                cls.add_material_to_obj(obj, idname)
    
    @classmethod
    def remove(cls, objects, idnames, from_file=False):
        cls.replace(objects, idnames, "", from_file)
    
    @classmethod
    def replace(cls, objects, src_idnames, dst_idname, from_file=False, purge=False):
        idnames = cls.split_idnames(src_idnames)
        dst_material = cls.to_material(dst_idname)
        
        replaced_idnames = set()
        
        if not from_file:
            for obj in objects:
                for ms in obj.material_slots:
                    if (idnames is None) or (ms.name in idnames):
                        if ms.name: replaced_idnames.add(ms.name)
                        ms.link = 'OBJECT'
                        ms.material = dst_material
        else:
            for obj in bpy.data.objects:
                for ms in obj.material_slots:
                    if (idnames is None) or (ms.name in idnames):
                        if ms.name: replaced_idnames.add(ms.name)
                        ms.material = dst_material
            
            for datas in (bpy.data.meshes, bpy.data.curves, bpy.data.metaballs):
                for data in datas:
                    for i in range(len(data.materials)):
                        mat = data.materials[i]
                        if (idnames is None) or (mat and (mat.name in idnames)):
                            if mat and mat.name: replaced_idnames.add(mat.name)
                            data.materials[i] = dst_material
        
        replaced_idnames.discard(dst_idname)
        
        if purge and replaced_idnames:
            cls.set_attr("use_fake_user", False, None, replaced_idnames)
            for mat in tuple(bpy.data.materials):
                if mat.name in replaced_idnames:
                    bpy.data.materials.remove(mat)
    
    @classmethod
    def find_objects(cls, idnames, search_in, context=None):
        idnames = cls.split_idnames(idnames)
        for obj in cls.iterate_objects(search_in, context):
            if any((ms.name in idnames) for ms in obj.material_slots):
                yield obj
    
    @classmethod
    def select(cls, scene, idnames):
        idnames = cls.split_idnames(idnames)
        for obj in scene.objects:
            obj.select = any((ms.name in idnames) for ms in obj.material_slots)
    
    @classmethod
    def purge(cls, even_with_fake_users, idnames=None):
        if idnames is None:
            if even_with_fake_users:
                fake_idnames = (mat.name for mat in bpy.data.materials if mat.use_fake_user and (mat.users == 1))
                cls.set_attr("use_fake_user", False, None, fake_idnames)
            for mat in tuple(bpy.data.materials):
                if mat.users > 0: continue
                bpy.data.materials.remove(mat)
        else:
            cls.remove(None, idnames, True)
            cls.set_attr("use_fake_user", False, None, idnames)
            idnames = cls.split_idnames(idnames)
            for mat in tuple(bpy.data.materials):
                if mat.name in idnames:
                    bpy.data.materials.remove(mat)
    
    @classmethod
    def copy(cls, active_obj, exclude=()):
        if not active_obj:
            cls.clipbuffer = []
        else:
            cls.clipbuffer = [ms.name for ms in active_obj.material_slots if ms.material and (ms.name not in exclude)]
    
    @classmethod
    def paste(cls, objects, paste_mode):
        idnames = cls.clipbuffer
        if idnames is None: return
        if paste_mode != 'AND':
            for obj in objects:
                if paste_mode == 'SET': cls.clear_obj_materials(obj)
                for idname in idnames:
                    cls.add_material_to_obj(obj, idname)
        else:
            for obj in objects:
                cls.clear_obj_materials(obj, idnames, False)
    
    @classmethod
    def merge_identical(cls):
        unique = set(bpy.data.materials)
        identical = []
        ignore = {"name"}
        
        for item in bpy.data.materials:
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

make_category(globals(), is_ID=True, copy_paste_contexts={'MATERIAL'})
