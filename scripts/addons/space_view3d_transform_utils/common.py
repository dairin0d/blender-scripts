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

addon = AddonManager()

#============================================================================#

def LeftRightPanel(cls=None, **kwargs):
    def AddPanels(cls, kwargs):
        doc = cls.__doc__
        name = kwargs.get("bl_idname") or kwargs.get("idname") or cls.__name__
        
        # expected either class or function
        if not isinstance(cls, type):
            cls = type(name, (), dict(__doc__=doc, draw=cls))
        
        def is_panel_left():
            if not addon.preferences: return False
            return addon.preferences.use_panel_left
        def is_panel_right():
            if not addon.preferences: return False
            return addon.preferences.use_panel_right
        
        @addon.Panel(**kwargs)
        class LeftPanel(cls):
            bl_idname = name + "_left"
            bl_region_type = 'TOOLS'
        
        @addon.Panel(**kwargs)
        class RightPanel(cls):
            bl_idname = name + "_right"
            bl_region_type = 'UI'
        
        poll = getattr(cls, "poll", None)
        if poll:
            LeftPanel.poll = classmethod(lambda cls, context: is_panel_left() and poll(cls, context))
            RightPanel.poll = classmethod(lambda cls, context: is_panel_right() and poll(cls, context))
        else:
            LeftPanel.poll = classmethod(lambda cls, context: is_panel_left())
            RightPanel.poll = classmethod(lambda cls, context: is_panel_right())
        
        return cls
    
    if cls: return AddPanels(cls, kwargs)
    return (lambda cls: AddPanels(cls, kwargs))
