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

import bpy
import bgl
import blf
import bmesh

from mathutils import Vector, Matrix, Quaternion, Euler

from mathutils.geometry import (intersect_line_sphere,
                                intersect_ray_tri,
                                barycentric_transform,
                                tessellate_polygon,
                                intersect_line_line,
                                intersect_line_plane,
                                )

from bpy_extras.view3d_utils import (region_2d_to_location_3d,
                                     location_3d_to_region_2d,
                                     )

import math
import time

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_math import *
from {0}dairin0d.utils_ui import NestedLayout, tag_redraw
from {0}dairin0d.utils_view3d import SmartView3D
from {0}dairin0d.utils_userinput import KeyMapUtils
from {0}dairin0d.bpy_inspect import prop, BlRna, BlEnums
from {0}dairin0d.utils_blender import ToggleObjectMode, MeshCache
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

addon = AddonManager()

#============================================================================#

# ====== MODULE GLOBALS / CONSTANTS ====== #
tmp_name = chr(0x10ffff) # maximal Unicode value
epsilon = 0.000001

# ===== MATH / GEOMETRY UTILITIES ===== #
def prepare_grid_mesh(bm, nx=1, ny=1, sx=1.0, sy=1.0,
                      z=0.0, xyz_indices=(0,1,2)):
    vertices = []
    for i in range(nx + 1):
        x = 2 * (i / nx) - 1
        x *= sx
        for j in range(ny + 1):
            y = 2 * (j / ny) - 1
            y *= sy
            pos = (x, y, z)
            vert = bm.verts.new((pos[xyz_indices[0]],
                                 pos[xyz_indices[1]],
                                 pos[xyz_indices[2]]))
            vertices.append(vert)

    nxmax = nx + 1
    for i in range(nx):
        i1 = i + 1
        for j in range(ny):
            j1 = j + 1
            verts = [vertices[j + i * nxmax],
                     vertices[j1 + i * nxmax],
                     vertices[j1 + i1 * nxmax],
                     vertices[j + i1 * nxmax]]
            bm.faces.new(verts)
    #return

def prepare_gridbox_mesh(subdiv=1):
    bm = bmesh.new()

    sides = [
        (-1, (0,1,2)), # -Z
        (1, (1,0,2)), # +Z
        (-1, (1,2,0)), # -Y
        (1, (0,2,1)), # +Y
        (-1, (2,0,1)), # -X
        (1, (2,1,0)), # +X
        ]

    for side in sides:
        prepare_grid_mesh(bm, nx=subdiv, ny=subdiv,
            z=side[0], xyz_indices=side[1])

    return bm

# ===== UTILITY FUNCTIONS ===== #
cursor_stick_pos_cache = None
def update_stick_to_obj(context):
    global cursor_stick_pos_cache

    settings = find_settings()

    if not settings.stick_to_obj:
        cursor_stick_pos_cache = None
        return

    scene = context.scene

    settings_scene = scene.cursor_3d_tools_settings

    name = settings_scene.stick_obj_name
    if (not name) or (name not in scene.objects):
        cursor_stick_pos_cache = None
        return

    obj = scene.objects[name]
    pos = settings_scene.stick_obj_pos
    pos = obj.matrix_world * pos

    if pos != cursor_stick_pos_cache:
        cursor_stick_pos_cache = pos

        # THIS IS AN EXPENSIVE OPERATION!
        # (eats 50% of my CPU if called each frame)
        context.space_data.cursor_location = pos

def get_cursor_location(v3d=None, scene=None):
    if v3d:
        pos = v3d.cursor_location
    elif scene:
        pos = scene.cursor_location

    return pos.copy()

set_cursor_location__reset_stick = True
def set_cursor_location(pos, v3d=None, scene=None):
    pos = pos.to_3d().copy()

    if v3d:
        scene = bpy.context.scene
        # Accessing scene.cursor_location is SLOW
        # (well, at least assigning to it).
        # Accessing v3d.cursor_location is fast.
        v3d.cursor_location = pos
    elif scene:
        scene.cursor_location = pos

    if set_cursor_location__reset_stick:
        set_stick_obj(scene, None)

def set_stick_obj(scene, name=None, pos=None):
    settings_scene = scene.cursor_3d_tools_settings

    if name:
        settings_scene.stick_obj_name = name
    else:
        settings_scene.stick_obj_name = ""

    if pos is not None:
        settings_scene.stick_obj_pos = Vector(pos).to_3d()

# WHERE TO STORE SETTINGS:
# Currently there are two types of ID blocks
# which properties don't change on Undo/Redo.
# - WindowManager seems to be unique (at least
#   for majority of situations). However, the
#   properties stored in it are not saved
#   with the blend.
# - Screen. Properties are saved with blend,
#   but there is some probability that any of
#   the pre-chosen screen names may not exist
#   in the user's blend.

def propagate_settings_to_all_screens(settings):
    # At least the most vital "user preferences" stuff
    for screen in bpy.data.screens:
        _settings = screen.cursor_3d_tools_settings
        _settings.auto_register_keymaps = settings.auto_register_keymaps
        _settings.free_coord_precision = settings.free_coord_precision

def find_settings():
    #wm = bpy.data.window_managers[0]
    #settings = wm.cursor_3d_tools_settings

    try:
        screen = bpy.data.screens.get("Default", bpy.data.screens[0])
    except:
        # find_settings() was called from register()/unregister()
        screen = bpy.context.window_manager.windows[0].screen

    try:
        settings = screen.cursor_3d_tools_settings
    except:
        # addon was unregistered
        settings = None

    return settings

def find_runtime_settings():
    wm = bpy.data.window_managers[0]
    try:
        runtime_settings = wm.cursor_3d_runtime_settings
    except:
        # addon was unregistered
        runtime_settings = None

    return runtime_settings

def KeyMapItemSearch(idname, place=None):
    if isinstance(place, bpy.types.KeyMap):
        for kmi in place.keymap_items:
            if kmi.idname == idname:
                yield kmi
    elif isinstance(place, bpy.types.KeyConfig):
        for keymap in place.keymaps:
            for kmi in KeyMapItemSearch(idname, keymap):
                yield kmi
    else:
        wm = bpy.context.window_manager
        for keyconfig in wm.keyconfigs:
            for kmi in KeyMapItemSearch(idname, keyconfig):
                yield kmi

def IsKeyMapItemEvent(kmi, event):
    event_any = (event.shift or event.ctrl or event.alt or event.oskey)
    event_key_modifier = 'NONE' # no such info in event
    return ((kmi.type == event.type) and
            (kmi.value == event.value) and
            (kmi.shift == event.shift) and
            (kmi.ctrl == event.ctrl) and
            (kmi.alt == event.alt) and
            (kmi.oskey == event.oskey) and
            (kmi.any == event_any) and
            (kmi.key_modifier == event_key_modifier))

# ===== DRAWING UTILITIES ===== #
class GfxCell:
    def __init__(self, w, h, color=None, alpha=None, draw=None):
        self.w = w
        self.h = h

        self.color = (0, 0, 0, 1)
        self.set_color(color, alpha)

        if draw:
            self.draw = draw

    def set_color(self, color=None, alpha=None):
        if color is None:
            color = self.color
        if alpha is None:
            alpha = (color[3] if len(color) > 3 else self.color[3])
        self.color = Vector((color[0], color[1], color[2], alpha))

    def prepare_draw(self, x, y, align=(0, 0)):
        if self.color[3] <= 0.0:
            return None

        if (align[0] != 0) or (align[1] != 0):
            x -= self.w * align[0]
            y -= self.h * align[1]

        x = int(math.floor(x + 0.5))
        y = int(math.floor(y + 0.5))

        bgl.glColor4f(*self.color)

        return x, y

    def draw(self, x, y, align=(0, 0)):
        xy = self.prepare_draw(x, y, align)
        if not xy:
            return

        draw_rect(xy[0], xy[1], w, h)

class TextCell(GfxCell):
    font_id = 0

    def __init__(self, text="", color=None, alpha=None, font_id=None):
        if font_id is None:
            font_id = TextCell.font_id
        self.font_id = font_id

        self.set_text(text)

        self.color = (0, 0, 0, 1)
        self.set_color(color, alpha)

    def set_text(self, text):
        self.text = str(text)
        dims = blf.dimensions(self.font_id, self.text)
        self.w = dims[0]
        dims = blf.dimensions(self.font_id, "dp") # fontheight
        self.h = dims[1]

    def draw(self, x, y, align=(0, 0)):
        xy = self.prepare_draw(x, y, align)
        if not xy:
            return

        blf.position(self.font_id, xy[0], xy[1], 0)
        blf.draw(self.font_id, self.text)


def draw_text(x, y, value, font_id=0, align=(0, 0), font_height=None):
    value = str(value)

    if (align[0] != 0) or (align[1] != 0):
        dims = blf.dimensions(font_id, value)
        if font_height is not None:
            dims = (dims[0], font_height)
        x -= dims[0] * align[0]
        y -= dims[1] * align[1]

    x = int(math.floor(x + 0.5))
    y = int(math.floor(y + 0.5))

    blf.position(font_id, x, y, 0)
    blf.draw(font_id, value)

def draw_rect(x, y, w, h, margin=0, outline=False):
    if w < 0:
        x += w
        w = abs(w)

    if h < 0:
        y += h
        h = abs(h)

    x = int(x)
    y = int(y)
    w = int(w)
    h = int(h)
    margin = int(margin)

    if outline:
        bgl.glBegin(bgl.GL_LINE_LOOP)
    else:
        bgl.glBegin(bgl.GL_TRIANGLE_FAN)
    bgl.glVertex2i(x - margin, y - margin)
    bgl.glVertex2i(x + w + margin, y - margin)
    bgl.glVertex2i(x + w + margin, y + h + margin)
    bgl.glVertex2i(x - margin, y + h + margin)
    bgl.glEnd()

def append_round_rect(verts, x, y, w, h, rw, rh=None):
    if rh is None:
        rh = rw

    if w < 0:
        x += w
        w = abs(w)

    if h < 0:
        y += h
        h = abs(h)

    if rw < 0:
        rw = min(abs(rw), w * 0.5)
        x += rw
        w -= rw * 2

    if rh < 0:
        rh = min(abs(rh), h * 0.5)
        y += rh
        h -= rh * 2

    n = int(max(rw, rh) * math.pi / 2.0)

    a0 = 0.0
    a1 = math.pi / 2.0
    append_oval_segment(verts, x + w, y + h, rw, rh, a0, a1, n)

    a0 = math.pi / 2.0
    a1 = math.pi
    append_oval_segment(verts, x + w, y, rw, rh, a0, a1, n)

    a0 = math.pi
    a1 = 3.0 * math.pi / 2.0
    append_oval_segment(verts, x, y, rw, rh, a0, a1, n)

    a0 = 3.0 * math.pi / 2.0
    a1 = math.pi * 2.0
    append_oval_segment(verts, x, y + h, rw, rh, a0, a1, n)

def append_oval_segment(verts, x, y, rw, rh, a0, a1, n, skip_last=False):
    nmax = n - 1
    da = a1 - a0
    for i in range(n - int(skip_last)):
        a = a0 + da * (i / nmax)
        dx = math.sin(a) * rw
        dy = math.cos(a) * rh
        verts.append((x + int(dx), y + int(dy)))

def draw_line(p0, p1, c=None):
    if c is not None:
        bgl.glColor4f(c[0], c[1], c[2], \
            (c[3] if len(c) > 3 else 1.0))
    bgl.glBegin(bgl.GL_LINE_STRIP)
    bgl.glVertex3f(p0[0], p0[1], p0[2])
    bgl.glVertex3f(p1[0], p1[1], p1[2])
    bgl.glEnd()

def draw_line_2d(p0, p1, c=None):
    if c is not None:
        bgl.glColor4f(c[0], c[1], c[2], \
            (c[3] if len(c) > 3 else 1.0))
    bgl.glBegin(bgl.GL_LINE_STRIP)
    bgl.glVertex2f(p0[0], p0[1])
    bgl.glVertex2f(p1[0], p1[1])
    bgl.glEnd()

def draw_line_hidden_depth(p0, p1, c, a0=1.0, a1=0.5, s0=None, s1=None):
    bgl.glEnable(bgl.GL_DEPTH_TEST)
    bgl.glColor4f(c[0], c[1], c[2], a0)
    if s0 is not None:
        gl_enable(bgl.GL_LINE_STIPPLE, int(bool(s0)))
    draw_line(p0, p1)
    bgl.glDisable(bgl.GL_DEPTH_TEST)
    if (a1 == a0) and (s1 == s0):
        return
    bgl.glColor4f(c[0], c[1], c[2], a1)
    if s1 is not None:
        gl_enable(bgl.GL_LINE_STIPPLE, int(bool(s1)))
    draw_line(p0, p1)

def draw_arrow(p0, x, y, z, n_scl=0.2, ort_scl=0.035):
    p1 = p0 + z

    bgl.glBegin(bgl.GL_LINE_STRIP)
    bgl.glVertex3f(p0[0], p0[1], p0[2])
    bgl.glVertex3f(p1[0], p1[1], p1[2])
    bgl.glEnd()

    p2 = p1 - z * n_scl
    bgl.glBegin(bgl.GL_TRIANGLE_FAN)
    bgl.glVertex3f(p1[0], p1[1], p1[2])
    p3 = p2 + (x + y) * ort_scl
    bgl.glVertex3f(p3[0], p3[1], p3[2])
    p3 = p2 + (-x + y) * ort_scl
    bgl.glVertex3f(p3[0], p3[1], p3[2])
    p3 = p2 + (-x - y) * ort_scl
    bgl.glVertex3f(p3[0], p3[1], p3[2])
    p3 = p2 + (x - y) * ort_scl
    bgl.glVertex3f(p3[0], p3[1], p3[2])
    p3 = p2 + (x + y) * ort_scl
    bgl.glVertex3f(p3[0], p3[1], p3[2])
    bgl.glEnd()

def draw_arrow_2d(p0, n, L, arrow_len, arrow_width):
    p1 = p0 + n * L
    t = Vector((-n[1], n[0]))
    pA = p1 - n * arrow_len + t * arrow_width
    pB = p1 - n * arrow_len - t * arrow_width

    bgl.glBegin(bgl.GL_LINES)

    bgl.glVertex2f(p0[0], p0[1])
    bgl.glVertex2f(p1[0], p1[1])

    bgl.glVertex2f(p1[0], p1[1])
    bgl.glVertex2f(pA[0], pA[1])

    bgl.glVertex2f(p1[0], p1[1])
    bgl.glVertex2f(pB[0], pB[1])

    bgl.glEnd()

# Store/restore OpenGL settings and working with
# projection matrices -- inspired by space_view3d_panel_measure
# of Buerbaum Martin (Pontiac).

# OpenGl helper functions/data
gl_state_info = {
    bgl.GL_MATRIX_MODE:(bgl.GL_INT, 1),
    bgl.GL_PROJECTION_MATRIX:(bgl.GL_DOUBLE, 16),
    bgl.GL_LINE_WIDTH:(bgl.GL_FLOAT, 1),
    bgl.GL_BLEND:(bgl.GL_BYTE, 1),
    bgl.GL_LINE_STIPPLE:(bgl.GL_BYTE, 1),
    bgl.GL_COLOR:(bgl.GL_FLOAT, 4),
    bgl.GL_SMOOTH:(bgl.GL_BYTE, 1),
    bgl.GL_DEPTH_TEST:(bgl.GL_BYTE, 1),
    bgl.GL_DEPTH_WRITEMASK:(bgl.GL_BYTE, 1),
}
gl_type_getters = {
    bgl.GL_INT:bgl.glGetIntegerv,
    bgl.GL_DOUBLE:bgl.glGetFloatv, # ?
    bgl.GL_FLOAT:bgl.glGetFloatv,
    #bgl.GL_BYTE:bgl.glGetFloatv, # Why GetFloat for getting byte???
    bgl.GL_BYTE:bgl.glGetBooleanv, # maybe like that?
}

def gl_get(state_id):
    type, size = gl_state_info[state_id]
    buf = bgl.Buffer(type, [size])
    gl_type_getters[type](state_id, buf)
    return (buf if (len(buf) != 1) else buf[0])

def gl_enable(state_id, enable):
    if enable:
        bgl.glEnable(state_id)
    else:
        bgl.glDisable(state_id)

def gl_matrix_to_buffer(m):
    tempMat = [m[i][j] for i in range(4) for j in range(4)]
    return bgl.Buffer(bgl.GL_FLOAT, 16, tempMat)

# =========================== GATHER PARTICLES ============================= #
#============================================================================#
class Particle:
    pass

class View3D_Cursor(Particle):
    def __init__(self, context):
        assert context.space_data.type == 'VIEW_3D'
        self.v3d = context.space_data
        self.initial_pos = self.get_location()
        self.initial_matrix = Matrix.Translation(self.initial_pos)

    def revert(self):
        self.set_location(self.initial_pos)

    def get_location(self):
        return get_cursor_location(v3d=self.v3d)

    def set_location(self, value):
        set_cursor_location(Vector(value), v3d=self.v3d)

    def get_rotation(self):
        return Quaternion()

    def set_rotation(self, value):
        pass

    def get_scale(self):
        return Vector((1.0, 1.0, 1.0))

    def set_scale(self, value):
        pass

    def get_matrix(self):
        return Matrix.Translation(self.get_location())

    def set_matrix(self, value):
        self.set_location(value.to_translation())

    def get_initial_matrix(self):
        return self.initial_matrix

class View3D_Object(Particle):
    def __init__(self, obj):
        self.obj = obj

    def get_location(self):
        # obj.location seems to be in parent's system...
        # or even maybe not bounded by constraints %)
        return self.obj.matrix_world.to_translation()

class View3D_EditMesh_Vertex(Particle):
    pass

class View3D_EditMesh_Edge(Particle):
    pass

class View3D_EditMesh_Face(Particle):
    pass

class View3D_EditSpline_Point(Particle):
    pass

class View3D_EditSpline_BezierPoint(Particle):
    pass

class View3D_EditSpline_BezierHandle(Particle):
    pass

class View3D_EditMeta_Element(Particle):
    pass

class View3D_EditBone_Bone(Particle):
    pass

class View3D_EditBone_HeadTail(Particle):
    pass

class View3D_PoseBone(Particle):
    pass

class UV_Cursor(Particle):
    pass

class UV_Vertex(Particle):
    pass

class UV_Edge(Particle):
    pass

class UV_Face(Particle):
    pass

# Other types:
# NLA / Dopesheet / Graph editor ...

# Particles are used in the following situations:
# - as subjects of transformation
# - as reference point(s) for cursor transformation
# Note: particles 'dragged' by Proportional Editing
# are a separate issue (they can come and go).
def gather_particles(**kwargs):
    context = kwargs.get("context", bpy.context)

    area_type = kwargs.get("area_type", context.area.type)

    scene = kwargs.get("scene", context.scene)

    space_data = kwargs.get("space_data", context.space_data)
    region_data = kwargs.get("region_data", context.region_data)

    particles = []
    pivots = {}
    normal_system = None

    active_element = None
    cursor_pos = None
    median = None

    if area_type == 'VIEW_3D':
        context_mode = kwargs.get("context_mode", context.mode)

        selected_objects = kwargs.get("selected_objects",
            context.selected_objects)

        active_object = kwargs.get("active_object",
            context.active_object)

        if context_mode == 'OBJECT':
            for obj in selected_objects:
                particle = View3D_Object(obj)
                particles.append(particle)

            if active_object:
                active_element = active_object.\
                    matrix_world.to_translation()

        # On Undo/Redo scene hash value is changed ->
        # -> the monitor tries to update the CSU ->
        # -> object.mode_set seem to somehow conflict
        # with Undo/Redo mechanisms.
        elif active_object and active_object.data and \
        (context_mode in {
        'EDIT_MESH', 'EDIT_METABALL',
        'EDIT_CURVE', 'EDIT_SURFACE',
        'EDIT_ARMATURE', 'POSE'}):

            m = active_object.matrix_world

            positions = []
            normal = Vector((0, 0, 0))

            if context_mode == 'EDIT_MESH':
                bm = bmesh.from_edit_mesh(active_object.data)

                if bm.select_history:
                    elem = bm.select_history[-1]
                    if isinstance(elem, bmesh.types.BMVert):
                        active_element = elem.co.copy()
                    else:
                        active_element = Vector()
                        for v in elem.verts:
                            active_element += v.co
                        active_element *= 1.0 / len(elem.verts)

                for v in bm.verts:
                    if v.select:
                        positions.append(v.co)
                        normal += v.normal

                # mimic Blender's behavior (as of now,
                # order of selection is ignored)
                if len(positions) == 2:
                    normal = positions[1] - positions[0]
                elif len(positions) == 3:
                    a = positions[0] - positions[1]
                    b = positions[2] - positions[1]
                    normal = a.cross(b)
            elif context_mode == 'EDIT_METABALL':
                active_elem = active_object.data.elements.active
                if active_elem:
                    active_element = active_elem.co.copy()
                    active_element = active_object.\
                        matrix_world * active_element

                # Currently there is no API for element.select
                #for element in active_object.data.elements:
                #    if element.select:
                #        positions.append(element.co)
            elif context_mode == 'EDIT_ARMATURE':
                # active bone seems to have the same pivot
                # as median of the selection
                '''
                active_bone = active_object.data.edit_bones.active
                if active_bone:
                    active_element = active_bone.head + \
                                     active_bone.tail
                    active_element = active_object.\
                        matrix_world * active_element
                '''

                for bone in active_object.data.edit_bones:
                    if bone.select_head:
                        positions.append(bone.head)
                    if bone.select_tail:
                        positions.append(bone.tail)
            elif context_mode == 'POSE':
                active_bone = active_object.data.bones.active
                if active_bone:
                    active_element = active_bone.\
                        matrix_local.translation.to_3d()
                    active_element = active_object.\
                        matrix_world * active_element

                # consider only topmost parents
                bones = set()
                for bone in active_object.data.bones:
                    if bone.select:
                        bones.add(bone)

                parents = set()
                for bone in bones:
                    if not set(bone.parent_recursive).intersection(bones):
                        parents.add(bone)

                for bone in parents:
                    positions.append(bone.matrix_local.translation.to_3d())
            else:
                for spline in active_object.data.splines:
                    for point in spline.bezier_points:
                        if point.select_control_point:
                            positions.append(point.co)
                        else:
                            if point.select_left_handle:
                                positions.append(point.handle_left)
                            if point.select_right_handle:
                                positions.append(point.handle_right)

                        n = None
                        nL = point.co - point.handle_left
                        nR = point.co - point.handle_right
                        #nL = point.handle_left.copy()
                        #nR = point.handle_right.copy()
                        if point.select_control_point:
                            n = nL + nR
                        elif point.select_left_handle or \
                             point.select_right_handle:
                            n = nL + nR
                        else:
                            if point.select_left_handle:
                                n = -nL
                            if point.select_right_handle:
                                n = nR

                        if n is not None:
                            if n.length_squared < epsilon:
                                n = -nL
                            normal += n.normalized()

                    for point in spline.points:
                        if point.select:
                            positions.append(point.co)

            if len(positions) != 0:
                if normal.length_squared < epsilon:
                    normal = Vector((0, 0, 1))
                normal.rotate(m)
                normal.normalize()

                if (1.0 - abs(normal.z)) < epsilon:
                    t1 = Vector((1, 0, 0))
                else:
                    t1 = Vector((0, 0, 1)).cross(normal)
                t2 = t1.cross(normal)
                normal_system = matrix_compose(t1, t2, normal)

                median, bbox_center = calc_median_bbox_pivots(positions)
                median = m * median
                bbox_center = m * bbox_center

                # Currently I don't know how to get active mesh element
                if active_element is None:
                    if context_mode == 'EDIT_ARMATURE':
                        # Somewhy EDIT_ARMATURE has such behavior
                        active_element = bbox_center
                    else:
                        active_element = median
            else:
                if active_element is None:
                    active_element = active_object.\
                        matrix_world.to_translation()

                median = active_element
                bbox_center = active_element

                normal_system = active_object.matrix_world.to_3x3()
                normal_system.col[0].normalize()
                normal_system.col[1].normalize()
                normal_system.col[2].normalize()
        else:
            # paint/sculpt, etc.?
            particle = View3D_Object(active_object)
            particles.append(particle)

            if active_object:
                active_element = active_object.\
                    matrix_world.to_translation()

        cursor_pos = get_cursor_location(v3d=space_data)

    #elif area_type == 'IMAGE_EDITOR':
        # currently there is no way to get UV editor's
        # offset (and maybe some other parameters
        # required to implement these operators)
        #cursor_pos = space_data.uv_editor.cursor_location

    #elif area_type == 'EMPTY':
    #elif area_type == 'GRAPH_EDITOR':
    #elif area_type == 'OUTLINER':
    #elif area_type == 'PROPERTIES':
    #elif area_type == 'FILE_BROWSER':
    #elif area_type == 'INFO':
    #elif area_type == 'SEQUENCE_EDITOR':
    #elif area_type == 'TEXT_EDITOR':
    #elif area_type == 'AUDIO_WINDOW':
    #elif area_type == 'DOPESHEET_EDITOR':
    #elif area_type == 'NLA_EDITOR':
    #elif area_type == 'SCRIPTS_WINDOW':
    #elif area_type == 'TIMELINE':
    #elif area_type == 'NODE_EDITOR':
    #elif area_type == 'LOGIC_EDITOR':
    #elif area_type == 'CONSOLE':
    #elif area_type == 'USER_PREFERENCES':

    else:
        print("gather_particles() not implemented for '{}'".format(area_type))
        return None, None

    # 'INDIVIDUAL_ORIGINS' is not handled here

    if cursor_pos:
        pivots['CURSOR'] = cursor_pos.copy()

    if active_element:
        # in v3d: ACTIVE_ELEMENT
        pivots['ACTIVE'] = active_element.copy()

    if (len(particles) != 0) and (median is None):
        positions = (p.get_location() for p in particles)
        median, bbox_center = calc_median_bbox_pivots(positions)

    if median:
        # in v3d: MEDIAN_POINT, in UV editor: MEDIAN
        pivots['MEDIAN'] = median.copy()
        # in v3d: BOUNDING_BOX_CENTER, in UV editor: CENTER
        pivots['CENTER'] = bbox_center.copy()

    csu = CoordinateSystemUtility(scene, space_data, region_data, \
        pivots, normal_system)

    return particles, csu

def calc_median_bbox_pivots(positions):
    median = None # pos can be 3D or 2D
    bbox = [None, None]

    n = 0
    for pos in positions:
        extend_bbox(bbox, pos)
        try:
            median += pos
        except:
            median = pos.copy()
        n += 1

    median = median / n
    bbox_center = (Vector(bbox[0]) + Vector(bbox[1])) * 0.5

    return median, bbox_center

def extend_bbox(bbox, pos):
    try:
        bbox[0] = tuple(min(e0, e1) for e0, e1 in zip(bbox[0], pos))
        bbox[1] = tuple(max(e0, e1) for e0, e1 in zip(bbox[1], pos))
    except:
        bbox[0] = tuple(pos)
        bbox[1] = tuple(pos)

#============================================================================#
#============================================================================#

# ====== COORDINATE SYSTEM UTILITY ====== #
class CoordinateSystemUtility:
    pivot_name_map = {
        'CENTER':'CENTER',
        'BOUNDING_BOX_CENTER':'CENTER',
        'MEDIAN':'MEDIAN',
        'MEDIAN_POINT':'MEDIAN',
        'CURSOR':'CURSOR',
        'INDIVIDUAL_ORIGINS':'INDIVIDUAL',
        'ACTIVE_ELEMENT':'ACTIVE',
        'WORLD':'WORLD',
        'SURFACE':'SURFACE', # ?
        'BOOKMARK':'BOOKMARK',
    }
    pivot_v3d_map = {
        'CENTER':'BOUNDING_BOX_CENTER',
        'MEDIAN':'MEDIAN_POINT',
        'CURSOR':'CURSOR',
        'INDIVIDUAL':'INDIVIDUAL_ORIGINS',
        'ACTIVE':'ACTIVE_ELEMENT',
    }

    def __init__(self, scene, space_data, region_data, \
                 pivots, normal_system):
        self.space_data = space_data
        self.region_data = region_data

        if space_data.type == 'VIEW_3D':
            self.pivot_map_inv = self.pivot_v3d_map

        self.tou = TransformOrientationUtility(
            scene, space_data, region_data)
        self.tou.normal_system = normal_system

        self.pivots = pivots

        # Assigned by caller (for cursor or selection)
        self.source_pos = None
        self.source_rot = None
        self.source_scale = None

    def set_orientation(self, name):
        self.tou.set(name)

    def set_pivot(self, pivot):
        self.space_data.pivot_point = self.pivot_map_inv[pivot]

    def get_pivot_name(self, name=None, relative=None, raw=False):
        pivot = self.pivot_name_map[self.space_data.pivot_point]
        if raw:
            return pivot

        if not name:
            name = self.tou.get()

        if relative is None:
            settings = find_settings()
            tfm_opts = settings.transform_options
            relative = tfm_opts.use_relative_coords

        if relative:
            pivot = "RELATIVE"
        elif (name == 'GLOBAL') or (pivot == 'WORLD'):
            pivot = 'WORLD'
        elif (name == "Surface") or (pivot == 'SURFACE'):
            pivot = "SURFACE"

        return pivot

    def get_origin(self, name=None, relative=None, pivot=None):
        if not pivot:
            pivot = self.get_pivot_name(name, relative)

        if relative or (pivot == "RELATIVE"):
            # "relative" parameter overrides "pivot"
            return self.source_pos
        elif pivot == 'WORLD':
            return Vector()
        elif pivot == "SURFACE":
            runtime_settings = find_runtime_settings()
            return Vector(runtime_settings.surface_pos)
        else:
            if pivot == 'INDIVIDUAL':
                pivot = 'MEDIAN'

            #if pivot == 'ACTIVE':
            #    print(self.pivots)

            try:
                return self.pivots[pivot]
            except:
                return Vector()

    def get_matrix(self, name=None, relative=None, pivot=None):
        if not name:
            name = self.tou.get()

        matrix = self.tou.get_matrix(name)

        if isinstance(pivot, Vector):
            pos = pivot
        else:
            pos = self.get_origin(name, relative, pivot)

        return to_matrix4x4(matrix, pos)

# ====== TRANSFORM ORIENTATION UTILITIES ====== #
class TransformOrientationUtility:
    special_systems = {"Surface", "Scaled"}
    predefined_systems = {
        'GLOBAL', 'LOCAL', 'VIEW', 'NORMAL', 'GIMBAL',
        "Scaled", "Surface",
    }

    def __init__(self, scene, v3d, rv3d):
        self.scene = scene
        self.v3d = v3d
        self.rv3d = rv3d

        self.custom_systems = [item for item in scene.orientations \
            if item.name not in self.special_systems]

        self.is_custom = False
        self.custom_id = -1

        # This is calculated elsewhere
        self.normal_system = None

        self.set(v3d.transform_orientation)

    def get(self):
        return self.transform_orientation

    def get_title(self):
        if self.is_custom:
            return self.transform_orientation

        name = self.transform_orientation
        return name[:1].upper() + name[1:].lower()

    def set(self, name, set_v3d=True):
        if isinstance(name, int):
            n = len(self.custom_systems)
            if n == 0:
                # No custom systems, do nothing
                return

            increment = name

            if self.is_custom:
                # If already custom, switch to next custom system
                self.custom_id = (self.custom_id + increment) % n

            self.is_custom = True

            name = self.custom_systems[self.custom_id].name
        else:
            self.is_custom = name not in self.predefined_systems

            if self.is_custom:
                self.custom_id = next((i for i, v in \
                    enumerate(self.custom_systems) if v.name == name), -1)

            if name in self.special_systems:
                # Ensure such system exists
                self.get_custom(name)

        self.transform_orientation = name

        if set_v3d:
            self.v3d.transform_orientation = name

    def get_matrix(self, name=None):
        active_obj = self.scene.objects.active

        if not name:
            name = self.transform_orientation

        if self.is_custom:
            matrix = self.custom_systems[self.custom_id].matrix.copy()
        else:
            if (name == 'VIEW') and self.rv3d:
                matrix = self.rv3d.view_rotation.to_matrix()
            elif name == "Surface":
                matrix = self.get_custom(name).matrix.copy()
            elif (name == 'GLOBAL') or (not active_obj):
                matrix = Matrix().to_3x3()
            elif (name == 'NORMAL') and self.normal_system:
                matrix = self.normal_system.copy()
            else:
                matrix = active_obj.matrix_world.to_3x3()
                if name == "Scaled":
                    self.get_custom(name).matrix = matrix
                else: # 'LOCAL', 'GIMBAL', ['NORMAL'] for now
                    matrix[0].normalize()
                    matrix[1].normalize()
                    matrix[2].normalize()

        return matrix

    def get_custom(self, name):
        try:
            return self.scene.orientations[name]
        except:
            return create_transform_orientation(
                self.scene, name, Matrix())

# Is there a less cumbersome way to create transform orientation?
def create_transform_orientation(scene, name=None, matrix=None):
    active_obj = scene.objects.active
    prev_mode = None

    if active_obj:
        prev_mode = active_obj.mode
        bpy.ops.object.mode_set(mode='OBJECT')
    else:
        bpy.ops.object.add()

    # ATTENTION! This uses context's scene
    bpy.ops.transform.create_orientation()

    tfm_orient = scene.orientations[-1]

    if name is not None:
        basename = name
        i = 1
        while name in scene.orientations:
            name = "%s.%03i" % (basename, i)
            i += 1
        tfm_orient.name = name

    if matrix:
        tfm_orient.matrix = matrix.to_3x3()

    if active_obj:
        bpy.ops.object.mode_set(mode=prev_mode)
    else:
        bpy.ops.object.delete()

    return tfm_orient

# ====== VIEW UTILITY CLASS ====== #
class ViewUtility:
    methods = dict(
        get_locks = lambda: {},
        set_locks = lambda locks: None,
        get_position = lambda: Vector(),
        set_position = lambda: None,
        get_rotation = lambda: Quaternion(),
        get_direction = lambda: Vector((0, 0, 1)),
        get_viewpoint = lambda: Vector(),
        get_matrix = lambda: Matrix(),
        get_point = lambda xy, pos: \
            Vector((xy[0], xy[1], 0)),
        get_ray = lambda xy: tuple(
            Vector((xy[0], xy[1], 0)),
            Vector((xy[0], xy[1], 1)),
            False),
    )

    def __init__(self, region, space_data, region_data):
        self.region = region
        self.space_data = space_data
        self.region_data = region_data

        if space_data.type == 'VIEW_3D':
            self.implementation = View3DUtility(
                region, space_data, region_data)
        else:
            self.implementation = None

        if self.implementation:
            for name in self.methods:
                setattr(self, name,
                    getattr(self.implementation, name))
        else:
            for name, value in self.methods.items():
                setattr(self, name, value)

class View3DUtility:
    lock_types = {"lock_cursor": False, "lock_object": None, "lock_bone": ""}

    # ====== INITIALIZATION / CLEANUP ====== #
    def __init__(self, region, space_data, region_data):
        self.region = region
        self.space_data = space_data
        self.region_data = region_data

    # ====== GET VIEW MATRIX AND ITS COMPONENTS ====== #
    def get_locks(self):
        v3d = self.space_data
        return {k:getattr(v3d, k) for k in self.lock_types}

    def set_locks(self, locks):
        v3d = self.space_data
        for k in self.lock_types:
            setattr(v3d, k, locks.get(k, self.lock_types[k]))

    def _get_lock_obj_bone(self):
        v3d = self.space_data

        obj = v3d.lock_object
        if not obj:
            return None, None

        if v3d.lock_bone:
            try:
                # this is not tested!
                if obj.mode == 'EDIT':
                    bone = obj.data.edit_bones[v3d.lock_bone]
                else:
                    bone = obj.data.bones[v3d.lock_bone]
            except:
                bone = None

        return obj, bone

    # TODO: learn how to get these values from
    # rv3d.perspective_matrix and rv3d.view_matrix ?
    def get_position(self, no_locks=False):
        v3d = self.space_data
        rv3d = self.region_data

        if no_locks:
            return rv3d.view_location.copy()

        # rv3d.perspective_matrix and rv3d.view_matrix
        # seem to have some weird translation components %)

        if rv3d.view_perspective == 'CAMERA':
            p = v3d.camera.matrix_world.to_translation()
            d = self.get_direction()
            return p + d * rv3d.view_distance
        else:
            if v3d.lock_object:
                obj, bone = self._get_lock_obj_bone()
                if bone:
                    return (obj.matrix_world * bone.matrix).to_translation()
                else:
                    return obj.matrix_world.to_translation()
            elif v3d.lock_cursor:
                return get_cursor_location(v3d=v3d)
            else:
                return rv3d.view_location.copy()

    def set_position(self, pos, no_locks=False):
        v3d = self.space_data
        rv3d = self.region_data

        pos = pos.copy()

        if no_locks:
            rv3d.view_location = pos
            return

        if rv3d.view_perspective == 'CAMERA':
            d = self.get_direction()
            v3d.camera.matrix_world.translation = pos - d * rv3d.view_distance
        else:
            if v3d.lock_object:
                obj, bone = self._get_lock_obj_bone()
                if bone:
                    try:
                        bone.matrix.translation = \
                            obj.matrix_world.inverted() * pos
                    except:
                        # this is some degenerate object
                        bone.matrix.translation = pos
                else:
                    obj.matrix_world.translation = pos
            elif v3d.lock_cursor:
                set_cursor_location(pos, v3d=v3d)
            else:
                rv3d.view_location = pos

    def get_rotation(self):
        v3d = self.space_data
        rv3d = self.region_data

        if rv3d.view_perspective == 'CAMERA':
            return v3d.camera.matrix_world.to_quaternion()
        else:
            return rv3d.view_rotation

    def get_direction(self):
        # Camera (as well as viewport) looks in the direction of -Z;
        # Y is up, X is left
        d = self.get_rotation() * Vector((0, 0, -1))
        d.normalize()
        return d

    def get_viewpoint(self):
        v3d = self.space_data
        rv3d = self.region_data

        if rv3d.view_perspective == 'CAMERA':
            return v3d.camera.matrix_world.to_translation()
        else:
            p = self.get_position()
            d = self.get_direction()
            return p - d * rv3d.view_distance

    def get_matrix(self):
        m = self.get_rotation().to_matrix()
        m.resize_4x4()
        m.translation = self.get_viewpoint()
        return m

    def get_point(self, xy, pos):
        region = self.region
        rv3d = self.region_data
        return region_2d_to_location_3d(region, rv3d, xy, pos)

    def get_ray(self, xy):
        region = self.region
        v3d = self.space_data
        rv3d = self.region_data

        viewPos = self.get_viewpoint()
        viewDir = self.get_direction()

        near = viewPos + viewDir * v3d.clip_start
        far = viewPos + viewDir * v3d.clip_end

        a = region_2d_to_location_3d(region, rv3d, xy, near)
        b = region_2d_to_location_3d(region, rv3d, xy, far)

        # When viewed from in-scene camera, near and far
        # planes clip geometry even in orthographic mode.
        clip = rv3d.is_perspective or (rv3d.view_perspective == 'CAMERA')

        return a, b, clip

# ====== SNAP UTILITY CLASS ====== #
class SnapUtility:
    def __init__(self, context):
        if context.area.type == 'VIEW_3D':
            v3d = context.space_data
            shade = v3d.viewport_shade
            self.implementation = Snap3DUtility(context.scene, shade)
            self.implementation.update_targets(
                context.visible_objects, [])

    def dispose(self):
        self.implementation.dispose()

    def update_targets(self, to_include, to_exclude):
        self.implementation.update_targets(to_include, to_exclude)

    def set_modes(self, **kwargs):
        return self.implementation.set_modes(**kwargs)

    def snap(self, *args, **kwargs):
        return self.implementation.snap(*args, **kwargs)

class SnapUtilityBase:
    def __init__(self):
        self.targets = set()
        # TODO: set to current blend settings?
        self.interpolation = 'NEVER'
        self.editmode = False
        self.snap_type = None
        self.projection = [None, None, None]
        self.potential_snap_elements = None
        self.extra_snap_points = None

    def update_targets(self, to_include, to_exclude):
        self.targets.update(to_include)
        self.targets.difference_update(to_exclude)

    def set_modes(self, **kwargs):
        if "use_relative_coords" in kwargs:
            self.use_relative_coords = kwargs["use_relative_coords"]
        if "interpolation" in kwargs:
            # NEVER, ALWAYS, SMOOTH
            self.interpolation = kwargs["interpolation"]
        if "editmode" in kwargs:
            self.editmode = kwargs["editmode"]
        if "snap_align" in kwargs:
            self.snap_align = kwargs["snap_align"]
        if "snap_type" in kwargs:
            # 'INCREMENT', 'VERTEX', 'EDGE', 'FACE', 'VOLUME'
            self.snap_type = kwargs["snap_type"]
        if "axes_coords" in kwargs:
            # none, point, line, plane
            self.axes_coords = kwargs["axes_coords"]

    # ====== CURSOR REPOSITIONING ====== #
    def snap(self, xy, src_matrix, initial_matrix, do_raycast, \
        alt_snap, vu, csu, modify_Surface, use_object_centers):

        v3d = csu.space_data

        grid_step = self.grid_steps[alt_snap] * v3d.grid_scale

        su = self
        use_relative_coords = su.use_relative_coords
        snap_align = su.snap_align
        axes_coords = su.axes_coords
        snap_type = su.snap_type

        runtime_settings = find_runtime_settings()

        matrix = src_matrix.to_3x3()
        pos = src_matrix.to_translation().copy()

        sys_matrix = csu.get_matrix()
        if use_relative_coords:
            sys_matrix.translation = initial_matrix.translation.copy()

        # Axes of freedom and line/plane parameters
        start = Vector(((0 if v is None else v) for v in axes_coords))
        direction = Vector(((v is not None) for v in axes_coords))
        axes_of_freedom = 3 - int(sum(direction))

        # do_raycast is False when mouse is not moving
        if do_raycast:
            su.hide_bbox(True)

            self.potential_snap_elements = None
            self.extra_snap_points = None

            set_stick_obj(csu.tou.scene, None)

            raycast = None
            snap_to_obj = (snap_type != 'INCREMENT') #or use_object_centers
            snap_to_obj = snap_to_obj and (snap_type is not None)
            if snap_to_obj:
                a, b, clip = vu.get_ray(xy)
                view_dir = vu.get_direction()
                raycast = su.snap_raycast(a, b, clip, view_dir, csu, alt_snap)

            if raycast:
                surf_matrix, face_id, obj, orig_obj = raycast

                if not use_object_centers:
                    self.potential_snap_elements = [
                        (obj.matrix_world * obj.data.vertices[vi].co)
                        for vi in obj.data.tessfaces[face_id].vertices
                    ]

                if use_object_centers:
                    self.extra_snap_points = \
                        [obj.matrix_world.to_translation()]
                elif alt_snap:
                    pse = self.potential_snap_elements
                    n = len(pse)
                    if self.snap_type == 'EDGE':
                        self.extra_snap_points = []
                        for i in range(n):
                            v0 = pse[i]
                            v1 = pse[(i + 1) % n]
                            self.extra_snap_points.append((v0 + v1) / 2)
                    elif self.snap_type == 'FACE':
                        self.extra_snap_points = []
                        v0 = Vector()
                        for v1 in pse:
                            v0 += v1
                        self.extra_snap_points.append(v0 / n)

                if snap_align:
                    matrix = surf_matrix.to_3x3()

                if not use_object_centers:
                    pos = surf_matrix.to_translation()
                else:
                    pos = orig_obj.matrix_world.to_translation()

                try:
                    local_pos = orig_obj.matrix_world.inverted() * pos
                except:
                    # this is some degenerate object
                    local_pos = pos

                set_stick_obj(csu.tou.scene, orig_obj.name, local_pos)

                modify_Surface = modify_Surface and \
                    (snap_type != 'VOLUME') and (not use_object_centers)

                # === Update "Surface" orientation === #
                if modify_Surface:
                    # Use raycast[0], not matrix! If snap_align == False,
                    # matrix will be src_matrix!
                    coordsys = csu.tou.get_custom("Surface")
                    coordsys.matrix = surf_matrix.to_3x3()
                    runtime_settings.surface_pos = pos
                    if csu.tou.get() == "Surface":
                        sys_matrix = to_matrix4x4(matrix, pos)
            else:
                if axes_of_freedom == 0:
                    # Constrained in all axes, can't move.
                    pass
                elif axes_of_freedom == 3:
                    # Not constrained, move in view plane.
                    pos = vu.get_point(xy, pos)
                else:
                    a, b, clip = vu.get_ray(xy)
                    view_dir = vu.get_direction()

                    start = sys_matrix * start

                    if axes_of_freedom == 1:
                        direction = Vector((1, 1, 1)) - direction
                    direction.rotate(sys_matrix)

                    if axes_of_freedom == 2:
                        # Constrained in one axis.
                        # Find intersection with plane.
                        i_p = intersect_line_plane(a, b, start, direction)
                        if i_p is not None:
                            pos = i_p
                    elif axes_of_freedom == 1:
                        # Constrained in two axes.
                        # Find nearest point to line.
                        i_p = intersect_line_line(a, b, start,
                                                  start + direction)
                        if i_p is not None:
                            pos = i_p[1]
        #end if do_raycast

        try:
            sys_matrix_inv = sys_matrix.inverted()
        except:
            # this is some degenerate system
            sys_matrix_inv = Matrix()

        _pos = sys_matrix_inv * pos

        # don't snap when mouse hasn't moved
        if (snap_type == 'INCREMENT') and do_raycast:
            for i in range(3):
                _pos[i] = round_step(_pos[i], grid_step)

        for i in range(3):
            if axes_coords[i] is not None:
                _pos[i] = axes_coords[i]

        if (snap_type == 'INCREMENT') or (axes_of_freedom != 3):
            pos = sys_matrix * _pos

        res_matrix = to_matrix4x4(matrix, pos)

        CursorDynamicSettings.local_matrix = sys_matrix_inv * res_matrix

        return res_matrix

class Snap3DUtility(SnapUtilityBase):
    grid_steps = {False:1.0, True:0.1}

    cube_verts = [Vector((i, j, k))
        for i in (-1, 1)
        for j in (-1, 1)
        for k in (-1, 1)]

    def __init__(self, scene, shade):
        SnapUtilityBase.__init__(self)

        convert_types = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
        self.cache = MeshCache(scene, convert_types)

        # ? seems that dict is enough
        self.bbox_cache = {}#collections.OrderedDict()
        self.sys_matrix_key = [0.0] * 9

        bm = prepare_gridbox_mesh(subdiv=2)
        mesh = bpy.data.meshes.new(tmp_name)
        bm.to_mesh(mesh)
        mesh.update(calc_tessface=True)
        #mesh.calc_tessface()

        self.bbox_obj = self.cache._make_obj(mesh, None)
        self.bbox_obj.hide = True
        self.bbox_obj.draw_type = 'WIRE'
        self.bbox_obj.name = "BoundBoxSnap"

        self.shade_bbox = (shade == 'BOUNDBOX')

    def update_targets(self, to_include, to_exclude):
        settings = find_settings()
        tfm_opts = settings.transform_options
        only_solid = tfm_opts.snap_only_to_solid

        # Ensure this is a set and not some other
        # type of collection
        to_exclude = set(to_exclude)

        for target in to_include:
            if only_solid and ((target.draw_type == 'BOUNDS') \
                    or (target.draw_type == 'WIRE')):
                to_exclude.add(target)

        SnapUtilityBase.update_targets(self, to_include, to_exclude)

    def dispose(self):
        self.hide_bbox(True)

        mesh = self.bbox_obj.data
        bpy.data.objects.remove(self.bbox_obj)
        bpy.data.meshes.remove(mesh)

        self.cache.clear()

    def hide_bbox(self, hide):
        if self.bbox_obj.hide == hide:
            return

        self.bbox_obj.hide = hide

        # We need to unlink bbox until required to show it,
        # because otherwise outliner will blink each
        # time cursor is clicked
        if hide:
            self.cache.scene.objects.unlink(self.bbox_obj)
        else:
            self.cache.scene.objects.link(self.bbox_obj)

    def get_bbox_obj(self, obj, sys_matrix, sys_matrix_inv, is_local):
        if is_local:
            bbox = None
        else:
            bbox = self.bbox_cache.get(obj, None)

        if bbox is None:
            m = obj.matrix_world
            if is_local:
                sys_matrix = m.copy()
                try:
                    sys_matrix_inv = sys_matrix.inverted()
                except Exception:
                    # this is some degenerate system
                    sys_matrix_inv = Matrix()
            m_combined = sys_matrix_inv * m
            bbox = [None, None]

            variant = ('RAW' if (self.editmode and
                       (obj.type == 'MESH') and (obj.mode == 'EDIT'))
                       else 'PREVIEW')
            mesh_obj = self.cache.get(obj, variant, reuse=False)
            if (mesh_obj is None) or self.shade_bbox or \
                    (obj.draw_type == 'BOUNDS'):
                if is_local:
                    bbox = [(-1, -1, -1), (1, 1, 1)]
                else:
                    for p in self.cube_verts:
                        extend_bbox(bbox, m_combined * p.copy())
            elif is_local:
                bbox = [mesh_obj.bound_box[0], mesh_obj.bound_box[6]]
            else:
                for v in mesh_obj.data.vertices:
                    extend_bbox(bbox, m_combined * v.co.copy())

            bbox = (Vector(bbox[0]), Vector(bbox[1]))

            if not is_local:
                self.bbox_cache[obj] = bbox

        half = (bbox[1] - bbox[0]) * 0.5

        m = matrix_compose(half[0], half[1], half[2])
        m = sys_matrix.to_3x3() * m
        m.resize_4x4()
        m.translation = sys_matrix * (bbox[0] + half)
        self.bbox_obj.matrix_world = m

        return self.bbox_obj

    # TODO: ?
    # - Sort snap targets according to raycasted distance?
    # - Ignore targets if their bounding sphere is further
    #   than already picked position?
    # Perhaps these "optimizations" aren't worth the overhead.

    def raycast(self, a, b, clip, view_dir, is_bbox, \
                sys_matrix, sys_matrix_inv, is_local, x_ray):
        # If we need to interpolate normals or snap to
        # vertices/edges, we must convert mesh.
        #force = (self.interpolation != 'NEVER') or \
        #    (self.snap_type in {'VERTEX', 'EDGE'})
        # Actually, we have to always convert, since
        # we need to get face at least to find tangential.
        force = True
        edit = self.editmode

        res = None
        L = None

        for obj in self.targets:
            orig_obj = obj

            if obj.name == self.bbox_obj.name:
                # is there a better check?
                # ("a is b" doesn't work here)
                continue
            if obj.show_x_ray != x_ray:
                continue

            if is_bbox:
                obj = self.get_bbox_obj(obj, \
                    sys_matrix, sys_matrix_inv, is_local)
            elif obj.draw_type == 'BOUNDS':
                # Outside of BBox, there is no meaningful visual snapping
                # for such display mode
                continue

            m = obj.matrix_world.copy()
            try:
                mi = m.inverted()
            except:
                # this is some degenerate object
                continue
            la = mi * a
            lb = mi * b

            # Bounding sphere check (to avoid unnecesary conversions
            # and to make ray 'infinite')
            bb_min = Vector(obj.bound_box[0])
            bb_max = Vector(obj.bound_box[6])
            c = (bb_min + bb_max) * 0.5
            r = (bb_max - bb_min).length * 0.5
            sec = intersect_line_sphere(la, lb, c, r, False)
            if sec[0] is None:
                continue # no intersection with the bounding sphere

            if not is_bbox:
                # Ensure we work with raycastable object.
                variant = ('RAW' if (edit and
                           (obj.type == 'MESH') and (obj.mode == 'EDIT'))
                           else 'PREVIEW')
                obj = self.cache.get(obj, variant, reuse=(not force))
                if (obj is None) or (not obj.data.polygons):
                    continue # the object has no raycastable geometry

            # If ray must be infinite, ensure that
            # endpoints are outside of bounding volume
            if not clip:
                # Seems that intersect_line_sphere()
                # returns points in flipped order
                lb, la = sec

            # Does ray actually intersect something?
            try:
                lp, ln, face_id = obj.ray_cast(la, lb)
            except Exception as e:
                # Somewhy this seems to happen when snapping cursor
                # in Local View mode at least since r55223:
                # <<Object "\U0010ffff" has no mesh data to be used
                # for raycasting>> despite obj.data.polygons
                # being non-empty.
                try:
                    # Work-around: in Local View at least the object
                    # in focus permits raycasting (modifiers are
                    # applied in 'PREVIEW' mode)
                    lp, ln, face_id = orig_obj.ray_cast(la, lb)
                except Exception as e:
                    # However, in Edit mode in Local View we have
                    # no luck -- during the edit mode, mesh is
                    # inaccessible (thus no mesh data for raycasting).
                    #print(repr(e))
                    face_id = -1

            if face_id == -1:
                continue

            # transform position to global space
            p = m * lp

            # This works both for prespective and ortho
            l = p.dot(view_dir)
            if (L is None) or (l < L):
                res = (lp, ln, face_id, obj, p, m, la, lb, orig_obj)
                L = l
        #end for

        return res

    # Returns:
    # Matrix(X -- tangential,
    #        Y -- 2nd tangential,
    #        Z -- normal,
    #        T -- raycasted/snapped position)
    # Face ID (-1 if not applicable)
    # Object (None if not applicable)
    def snap_raycast(self, a, b, clip, view_dir, csu, alt_snap):
        settings = find_settings()
        tfm_opts = settings.transform_options

        if self.shade_bbox and tfm_opts.snap_only_to_solid:
            return None

        # Since introduction of "use object centers",
        # this check is useless (use_object_centers overrides
        # even INCREMENT snapping)
        #if self.snap_type not in {'VERTEX', 'EDGE', 'FACE', 'VOLUME'}:
        #    return None

        # key shouldn't depend on system origin;
        # for bbox calculation origin is always zero
        #if csu.tou.get() != "Surface":
        #    sys_matrix = csu.get_matrix().to_3x3()
        #else:
        #    sys_matrix = csu.get_matrix('LOCAL').to_3x3()
        sys_matrix = csu.get_matrix().to_3x3()
        sys_matrix_key = list(c for v in sys_matrix for c in v)
        sys_matrix_key.append(self.editmode)
        sys_matrix = sys_matrix.to_4x4()
        try:
            sys_matrix_inv = sys_matrix.inverted()
        except:
            # this is some degenerate system
            return None

        if self.sys_matrix_key != sys_matrix_key:
            self.bbox_cache.clear()
            self.sys_matrix_key = sys_matrix_key

        # In this context, Volume represents BBox :P
        is_bbox = (self.snap_type == 'VOLUME')
        is_local = (csu.tou.get() in \
            {'LOCAL', "Scaled"})

        res = self.raycast(a, b, clip, view_dir, \
            is_bbox, sys_matrix, sys_matrix_inv, is_local, True)

        if res is None:
            res = self.raycast(a, b, clip, view_dir, \
                is_bbox, sys_matrix, sys_matrix_inv, is_local, False)

        # Occlusion-based edge/vertex snapping will be
        # too inefficient in Python (well, even without
        # the occlusion, iterating over all edges/vertices
        # of each object is inefficient too)

        if not res:
            return None

        lp, ln, face_id, obj, p, m, la, lb, orig_obj = res

        if is_bbox:
            self.bbox_obj.matrix_world = m.copy()
            self.bbox_obj.show_x_ray = orig_obj.show_x_ray
            self.hide_bbox(False)

        _ln = ln.copy()

        face = obj.data.tessfaces[face_id]
        L = None
        t1 = None

        if self.snap_type == 'VERTEX' or self.snap_type == 'VOLUME':
            for v0 in face.vertices:
                v = obj.data.vertices[v0]
                p0 = v.co
                l = (lp - p0).length_squared
                if (L is None) or (l < L):
                    p = p0
                    ln = v.normal.copy()
                    #t1 = ln.cross(_ln)
                    L = l

            _ln = ln.copy()
            '''
            if t1.length < epsilon:
                if (1.0 - abs(ln.z)) < epsilon:
                    t1 = Vector((1, 0, 0))
                else:
                    t1 = Vector((0, 0, 1)).cross(_ln)
            '''
            p = m * p
        elif self.snap_type == 'EDGE':
            use_smooth = face.use_smooth
            if self.interpolation == 'NEVER':
                use_smooth = False
            elif self.interpolation == 'ALWAYS':
                use_smooth = True

            for v0, v1 in face.edge_keys:
                p0 = obj.data.vertices[v0].co
                p1 = obj.data.vertices[v1].co
                dp = p1 - p0
                q = dp.dot(lp - p0) / dp.length_squared
                if (q >= 0.0) and (q <= 1.0):
                    ep = p0 + dp * q
                    l = (lp - ep).length_squared
                    if (L is None) or (l < L):
                        if alt_snap:
                            p = (p0 + p1) * 0.5
                            q = 0.5
                        else:
                            p = ep
                        if not use_smooth:
                            q = 0.5
                        ln = obj.data.vertices[v1].normal * q + \
                             obj.data.vertices[v0].normal * (1.0 - q)
                        t1 = dp
                        L = l

            p = m * p
        else:
            if alt_snap:
                lp = face.center
                p = m * lp

            if self.interpolation != 'NEVER':
                ln = self.interpolate_normal(
                    obj, face_id, lp, la, lb - la)

            # Comment this to make 1st tangential
            # always lie in the face's plane
            _ln = ln.copy()

            '''
            for v0, v1 in face.edge_keys:
                p0 = obj.data.vertices[v0].co
                p1 = obj.data.vertices[v1].co
                dp = p1 - p0
                q = dp.dot(lp - p0) / dp.length_squared
                if (q >= 0.0) and (q <= 1.0):
                    ep = p0 + dp * q
                    l = (lp - ep).length_squared
                    if (L is None) or (l < L):
                        t1 = dp
                        L = l
            '''

        n = ln.copy()
        n.rotate(m)
        n.normalize()

        if t1 is None:
            _ln.rotate(m)
            _ln.normalize()
            if (1.0 - abs(_ln.z)) < epsilon:
                t1 = Vector((1, 0, 0))
            else:
                t1 = Vector((0, 0, 1)).cross(_ln)
            t1.normalize()
        else:
            t1.rotate(m)
            t1.normalize()

        t2 = t1.cross(n)
        t2.normalize()

        matrix = matrix_compose(t1, t2, n, p)

        return (matrix, face_id, obj, orig_obj)

    def interpolate_normal(self, obj, face_id, p, orig, ray):
        face = obj.data.tessfaces[face_id]

        use_smooth = face.use_smooth
        if self.interpolation == 'NEVER':
            use_smooth = False
        elif self.interpolation == 'ALWAYS':
            use_smooth = True

        if not use_smooth:
            return face.normal.copy()

        # edge.use_edge_sharp affects smoothness only if
        # mesh has EdgeSplit modifier

        # ATTENTION! Coords/Normals MUST be copied
        # (a bug in barycentric_transform implementation ?)
        # Somewhat strangely, the problem also disappears
        # if values passed to barycentric_transform
        # are print()ed beforehand.

        co = [obj.data.vertices[vi].co.copy()
            for vi in face.vertices]

        normals = [obj.data.vertices[vi].normal.copy()
            for vi in face.vertices]

        if len(face.vertices) != 3:
            tris = tessellate_polygon([co])
            for tri in tris:
                i0, i1, i2 = tri
                if intersect_ray_tri(co[i0], co[i1], co[i2], ray, orig):
                    break
        else:
            i0, i1, i2 = 0, 1, 2

        n = barycentric_transform(p, co[i0], co[i1], co[i2],
            normals[i0], normals[i1], normals[i2])
        n.normalize()

        return n

# ===== TRANSFORM EXTRA OPTIONS ===== #
@addon.PropertyGroup
class TransformExtraOptionsProp:
    use_relative_coords = True | prop("Consider existing transformation as the starting point", "Relative coordinates")
    snap_interpolate_normals_mode = 'SMOOTH' | prop("Normal interpolation mode for snapping", "Normal interpolation", items=[
        ('NEVER', "Never", "Don't interpolate normals"),
        ('ALWAYS', "Always", "Always interpolate normals"),
        ('SMOOTH', "Smoothness-based", "Interpolate normals only for faces with smooth shading"),
    ])
    snap_only_to_solid = False | prop("Ignore wireframe/non-solid objects during snapping", "Snap only to solid")
    snap_element_screen_size = 8 | prop("Radius in pixels for snapping to edges/vertices", "Snap distance", min=2, max=64)
    use_comma_separator = True | prop("Use comma separator when copying/pasting coordinate values (instead of Tab character)", "Use comma separator")

# ===== 3D VECTOR LOCATION ===== #
@addon.PropertyGroup
class LocationProp:
    pos = Vector() | prop("xyz coords", "xyz")

# ===== HISTORY ===== #
def update_history_max_size(self, context):
    settings = find_settings()

    history = settings.history

    prop_class, prop_params = type(history).current_id
    old_max = prop_params["max"]

    size = history.max_size
    try:
        int_size = int(size)
        int_size = max(int_size, 0)
        int_size = min(int_size, history.max_size_limit)
    except:
        int_size = old_max

    if old_max != int_size:
        prop_params["max"] = int_size
        type(history).current_id = (prop_class, prop_params)

    # also: clear immediately?
    for i in range(len(history.entries) - 1, int_size, -1):
        history.entries.remove(i)

    if str(int_size) != size:
        # update history.max_size if it's not inside the limits
        history.max_size = str(int_size)

def update_history_id(self, context):
    scene = bpy.context.scene

    settings = find_settings()
    history = settings.history

    pos = history.get_pos()
    if pos is not None:
        # History doesn't depend on view (?)
        cursor_pos = get_cursor_location(scene=scene)

        if CursorHistoryProp.update_cursor_on_id_change:
            # Set cursor position anyway (we're changing v3d's
            # cursor, which may be separate from scene's)
            # This, however, should be done cautiously
            # from scripts, since, e.g., CursorMonitor
            # can supply wrong context -> cursor will be set
            # in a different view than required
            set_cursor_location(pos, v3d=context.space_data)

        if pos != cursor_pos:
            if (history.current_id == 0) and (history.last_id <= 1):
                history.last_id = 1
            else:
                history.last_id = history.curr_id
            history.curr_id = history.current_id

@addon.PropertyGroup
class CursorHistoryProp:
    max_size_limit = 500
    
    update_cursor_on_id_change = True
    
    show_trace = False | prop("Show history trace", "Trace")
    max_size = "50" | prop("History max size", "Size", update=update_history_max_size)
    current_id = 50 | prop("Current position in cursor location history", "Index", min=0, max=50)
    entries = [LocationProp] | prop()

    curr_id = bpy.props.IntProperty(options={'HIDDEN'})
    last_id = bpy.props.IntProperty(options={'HIDDEN'})

    def get_pos(self, id = None):
        if id is None:
            id = self.current_id

        id = min(max(id, 0), len(self.entries) - 1)

        if id < 0:
            # history is empty
            return None

        return self.entries[id].pos

    # for updating the upper bound on file load
    def update_max_size(self):
        prop_class, prop_params = type(self).current_id
        # self.max_size expected to be always a correct integer
        prop_params["max"] = int(self.max_size)
        type(self).current_id = (prop_class, prop_params)

    def draw_trace(self, context):
        bgl.glColor4f(0.75, 1.0, 0.75, 1.0)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for entry in self.entries:
            p = entry.pos
            bgl.glVertex3f(p[0], p[1], p[2])
        bgl.glEnd()

    def draw_offset(self, context):
        bgl.glShadeModel(bgl.GL_SMOOTH)

        tfm_operator = CursorDynamicSettings.active_transform_operator

        bgl.glBegin(bgl.GL_LINE_STRIP)

        if tfm_operator:
            p = tfm_operator.particles[0]. \
                get_initial_matrix().to_translation()
        else:
            p = self.get_pos(self.last_id)
        bgl.glColor4f(1.0, 0.75, 0.5, 1.0)
        bgl.glVertex3f(p[0], p[1], p[2])

        p = get_cursor_location(v3d=context.space_data)
        bgl.glColor4f(1.0, 1.0, 0.25, 1.0)
        bgl.glVertex3f(p[0], p[1], p[2])

        bgl.glEnd()

#============================================================================#

# A base class for emulating ID-datablock behavior
@addon.PropertyGroup
class PseudoIDBlockBase:
    # TODO: use normal metaprogramming?

    @staticmethod
    def create_props(type, name, options={'ANIMATABLE'}):
        def active_update(self, context):
            # necessary to avoid recursive calls
            if self._self_update[0]:
                return

            if self._dont_rename[0]:
                return

            if len(self.collection) == 0:
                return

            # prepare data for renaming...
            old_key = (self.enum if self.enum else self.collection[0].name)
            new_key = (self.active if self.active else "Untitled")

            if old_key == new_key:
                return

            old_item = None
            new_item = None
            existing_names = []

            for item in self.collection:
                if (item.name == old_key) and (not new_item):
                    new_item = item
                elif (item.name == new_key) and (not old_item):
                    old_item = item
                else:
                    existing_names.append(item.name)
            existing_names.append(new_key)

            # rename current item
            new_item.name = new_key

            if old_item:
                # rename other item if it has that name
                name = new_key
                i = 1
                while name in existing_names:
                    name = "{}.{:0>3}".format(new_key, i)
                    i += 1
                old_item.name = name

            # update the enum
            self._self_update[0] += 1
            self.update_enum()
            self._self_update[0] -= 1
        # end def

        def enum_update(self, context):
            # necessary to avoid recursive calls
            if self._self_update[0]:
                return

            self._dont_rename[0] = True
            self.active = self.enum
            self._dont_rename[0] = False

            self.on_item_select()
        # end def

        collection = bpy.props.CollectionProperty(
            type=type)
        active = bpy.props.StringProperty(
            name="Name",
            description="Name of the active {}".format(name),
            options=options,
            update=active_update)
        enum = bpy.props.EnumProperty(
            items=[],
            name="Choose",
            description="Choose {}".format(name),
            default=set(),
            options={'ENUM_FLAG'},
            update=enum_update)

        return collection, active, enum
    # end def

    def add(self, name="", **kwargs):
        if not name:
            name = 'Untitled'
        _name = name

        existing_names = [item.name for item in self.collection]
        i = 1
        while name in existing_names:
            name = "{}.{:0>3}".format(_name, i)
            i += 1

        instance = self.collection.add()
        instance.name = name

        for key, value in kwargs.items():
            setattr(instance, key, value)

        self._self_update[0] += 1
        self.active = name
        self.update_enum()
        self._self_update[0] -= 1

        return instance

    def remove(self, key):
        if isinstance(key, int):
            i = key
        else:
            i = self.indexof(key)

        # Currently remove() ignores non-existing indices...
        # In the case this behavior changes, we have the try block.
        try:
            self.collection.remove(i)
        except:
            pass

        self._self_update[0] += 1
        if len(self.collection) != 0:
            i = min(i, len(self.collection) - 1)
            self.active = self.collection[i].name
        else:
            self.active = ""
        self.update_enum()
        self._self_update[0] -= 1

    def get_item(self, key=None):
        if key is None:
            i = self.indexof(self.active)
        elif isinstance(key, int):
            i = key
        else:
            i = self.indexof(key)

        try:
            return self.collection[i]
        except:
            return None

    def indexof(self, key):
        return next((i for i, v in enumerate(self.collection) \
            if v.name == key), -1)

        # Which is more Pythonic?

        #for i, item in enumerate(self.collection):
        #    if item.name == key:
        #        return i
        #return -1 # non-existing index

    def update_enum(self):
        names = []
        items = []
        for item in self.collection:
            names.append(item.name)
            items.append((item.name, item.name, ""))

        prop_class, prop_params = type(self).enum
        prop_params["items"] = items
        if len(items) == 0:
            prop_params["default"] = set()
            prop_params["options"] = {'ENUM_FLAG'}
        else:
            # Somewhy active may be left from previous times,
            # I don't want to dig now why that happens.
            if self.active not in names:
                self.active = items[0][0]
            prop_params["default"] = self.active
            prop_params["options"] = set()

        # Can this cause problems? In the near future, shouldn't...
        type(self).enum = (prop_class, prop_params)
        #type(self).enum = bpy.props.EnumProperty(**prop_params)

        if len(items) != 0:
            self.enum = self.active

    def on_item_select(self):
        pass

    data_name = ""
    op_new = ""
    op_delete = ""
    icon = 'DOT'

    def draw(self, context, layout):
        if len(self.collection) == 0:
            if self.op_new:
                layout.operator(self.op_new, icon=self.icon)
            else:
                layout.label(
                    text="({})".format(self.data_name),
                    icon=self.icon)
            return

        row = layout.row(align=True)
        row.prop_menu_enum(self, "enum", text="", icon=self.icon)
        row.prop(self, "active", text="")
        if self.op_new:
            row.operator(self.op_new, text="", icon='ZOOMIN')
        if self.op_delete:
            row.operator(self.op_delete, text="", icon='X')
# end class

#============================================================================#

# ===== BOOKMARK ===== #
@addon.PropertyGroup
class BookmarkProp:
    name = "" | prop("bookmark name", "name")
    pos = Vector() | prop("xyz coords", "xyz")

@addon.PropertyGroup
class BookmarkIDBlock(PseudoIDBlockBase):
    # Somewhy instance members aren't seen in update()
    # callbacks... but class members are.
    _self_update = [0]
    _dont_rename = [False]

    data_name = "Bookmark"
    op_new = "scene.cursor_3d_new_bookmark"
    op_delete = "scene.cursor_3d_delete_bookmark"
    icon = 'CURSOR'

    collection, active, enum = PseudoIDBlockBase.create_props(BookmarkProp, "Bookmark")

@addon.Operator(idname="scene.cursor_3d_new_bookmark", label="New Bookmark", description="Add a new bookmark")
class NewCursor3DBookmark:
    name = "Mark" | prop("Name of the new bookmark", "Name")

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        bookmark = library.bookmarks.add(name=self.name)

        cusor_pos = get_cursor_location(v3d=context.space_data)

        try:
            bookmark.pos = library.convert_from_abs(context.space_data,
                                                    cusor_pos, True)
        except Exception as exc:
            self.report({'ERROR_INVALID_CONTEXT'}, exc.args[0])
            return {'CANCELLED'}

        return {'FINISHED'}

@addon.Operator(idname="scene.cursor_3d_delete_bookmark", label="Delete Bookmark", description="Delete active bookmark")
class DeleteCursor3DBookmark:
    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        name = library.bookmarks.active

        library.bookmarks.remove(key=name)

        return {'FINISHED'}

@addon.Operator(idname="scene.cursor_3d_overwrite_bookmark", label="Overwrite", description="Overwrite active bookmark with the current cursor location")
class OverwriteCursor3DBookmark:
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        bookmark = library.bookmarks.get_item()
        if not bookmark:
            return {'CANCELLED'}

        cusor_pos = get_cursor_location(v3d=context.space_data)

        try:
            bookmark.pos = library.convert_from_abs(context.space_data,
                                                    cusor_pos, True)
        except Exception as exc:
            self.report({'ERROR_INVALID_CONTEXT'}, exc.args[0])
            return {'CANCELLED'}

        CursorDynamicSettings.recalc_csu(context, 'PRESS')

        return {'FINISHED'}

@addon.Operator(idname="scene.cursor_3d_recall_bookmark", label="Recall", description="Move cursor to the active bookmark")
class RecallCursor3DBookmark:
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        bookmark = library.bookmarks.get_item()
        if not bookmark:
            return {'CANCELLED'}

        try:
            bookmark_pos = library.convert_to_abs(context.space_data,
                                                  bookmark.pos, True)
            set_cursor_location(bookmark_pos, v3d=context.space_data)
        except Exception as exc:
            self.report({'ERROR_INVALID_CONTEXT'}, exc.args[0])
            return {'CANCELLED'}

        CursorDynamicSettings.recalc_csu(context)

        return {'FINISHED'}

@addon.Operator(idname="scene.cursor_3d_swap_bookmark", label="Swap", description="Swap cursor position with the active bookmark")
class SwapCursor3DBookmark:
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        bookmark = library.bookmarks.get_item()
        if not bookmark:
            return {'CANCELLED'}

        cusor_pos = get_cursor_location(v3d=context.space_data)

        try:
            bookmark_pos = library.convert_to_abs(context.space_data,
                                                  bookmark.pos, True)

            set_cursor_location(bookmark_pos, v3d=context.space_data)

            bookmark.pos = library.convert_from_abs(context.space_data,
                                                    cusor_pos, True,
                use_history=False)
        except Exception as exc:
            self.report({'ERROR_INVALID_CONTEXT'}, exc.args[0])
            return {'CANCELLED'}

        CursorDynamicSettings.recalc_csu(context)

        return {'FINISHED'}

# Will this be used?
@addon.Operator(idname="scene.cursor_3d_snap_selection_to_bookmark", label="Snap Selection", description="Snap selection to the active bookmark")
class SnapSelectionToCursor3DBookmark:
    pass

# Will this be used?
@addon.Operator(idname="scene.cursor_3d_add_empty_at_bookmark", label="Add Empty", description="Add new Empty at the active bookmark")
class AddEmptyAtCursor3DBookmark:
    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        settings = find_settings()
        library = settings.libraries.get_item()
        if not library:
            return {'CANCELLED'}

        bookmark = library.bookmarks.get_item()
        if not bookmark:
            return {'CANCELLED'}

        try:
            matrix = library.get_matrix(use_history=False,
                                        v3d=context.space_data, warn=True)
            bookmark_pos = matrix * bookmark.pos
        except Exception as exc:
            self.report({'ERROR_INVALID_CONTEXT'}, exc.args[0])
            return {'CANCELLED'}

        name = "{}.{}".format(library.name, bookmark.name)
        obj = bpy.data.objects.new(name, None)
        obj.matrix_world = to_matrix4x4(matrix, bookmark_pos)
        context.scene.objects.link(obj)

        """
        for sel_obj in list(context.selected_objects):
            sel_obj.select = False
        obj.select = True
        context.scene.objects.active = obj

        # We need this to update bookmark position if
        # library's system is local/scaled/normal/etc.
        CursorDynamicSettings.recalc_csu(context, "PRESS")
        """

        # TODO: exit from editmode? It has separate history!
        # If we just link object to scene, it will not trigger
        # addition of new entry to Undo history
        bpy.ops.ed.undo_push(message="Add Object")

        return {'FINISHED'}

# ===== BOOKMARK LIBRARY ===== #
@addon.PropertyGroup
class BookmarkLibraryProp:
    name = "" | prop("Name of the bookmark library", "Name")
    bookmarks = BookmarkIDBlock | prop()
    system = 'GLOBAL' | prop("Coordinate system in which to store/recall cursor locations", "System", items=[
        ('GLOBAL', "Global", "Global (absolute) coordinates"),
        ('LOCAL', "Local", "Local coordinate system, relative to the active object"),
        ('SCALED', "Scaled", "Scaled local coordinate system, relative to the active object"),
        ('NORMAL', "Normal", "Normal coordinate system, relative to the selected elements"),
        ('CONTEXT', "Context", "Current transform orientation; origin depends on selection"),
    ])
    offset = False | prop("Store/recall relative to the last cursor position", "Offset")
    
    # Returned None means "operation is not aplicable"
    def get_matrix(self, use_history, v3d, warn=True, **kwargs):
        #particles, csu = gather_particles(**kwargs)

        # Ensure we have relevant CSU (Blender will crash
        # if we use the old one after Undo/Redo)
        CursorDynamicSettings.recalc_csu(bpy.context)

        csu = CursorDynamicSettings.csu

        if self.offset:
            # history? or keep separate for each scene?
            if not use_history:
                csu.source_pos = get_cursor_location(v3d=v3d)
            else:
                settings = find_settings()
                history = settings.history
                csu.source_pos = history.get_pos(history.last_id)
        else:
            csu.source_pos = Vector()

        active_obj = csu.tou.scene.objects.active

        if self.system == 'GLOBAL':
            sys_name = 'GLOBAL'
            pivot = 'WORLD'
        elif self.system == 'LOCAL':
            if not active_obj:
                if warn: raise Exception("There is no active object")
                return None
            sys_name = 'LOCAL'
            pivot = 'ACTIVE'
        elif self.system == 'SCALED':
            if not active_obj:
                if warn: raise Exception("There is no active object")
                return None
            sys_name = 'Scaled'
            pivot = 'ACTIVE'
        elif self.system == 'NORMAL':
            if not active_obj or active_obj.mode != 'EDIT':
                if warn: raise Exception("Active object must be in Edit mode")
                return None
            sys_name = 'NORMAL'
            pivot = 'MEDIAN' # ?
        elif self.system == 'CONTEXT':
            sys_name = None # use current orientation
            pivot = None

            if active_obj and (active_obj.mode != 'OBJECT'):
                if len(particles) == 0:
                    pivot = active_obj.matrix_world.to_translation()

        return csu.get_matrix(sys_name, self.offset, pivot)

    def convert_to_abs(self, v3d, pos, warn=False, **kwargs):
        kwargs.pop("use_history", None)
        matrix = self.get_matrix(False, v3d, warn, **kwargs)
        if not matrix:
            return None
        return matrix * pos

    def convert_from_abs(self, v3d, pos, warn=False, **kwargs):
        use_history = kwargs.pop("use_history", True)
        matrix = self.get_matrix(use_history, v3d, warn, **kwargs)
        if not matrix:
            return None

        try:
            return matrix.inverted() * pos
        except:
            # this is some degenerate object
            return Vector()

    def draw_bookmark(self, context):
        r = context.region
        rv3d = context.region_data

        bookmark = self.bookmarks.get_item()
        if not bookmark:
            return

        pos = self.convert_to_abs(context.space_data, bookmark.pos)
        if pos is None:
            return

        projected = location_3d_to_region_2d(r, rv3d, pos)

        if projected:
            # Store previous OpenGL settings
            smooth_prev = gl_get(bgl.GL_SMOOTH)

            pixelsize = 1
            dpi = context.user_preferences.system.dpi
            widget_unit = (pixelsize * dpi * 20.0 + 36.0) / 72.0

            bgl.glShadeModel(bgl.GL_SMOOTH)
            bgl.glLineWidth(2)
            bgl.glColor4f(0.0, 1.0, 0.0, 1.0)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            radius = widget_unit * 0.3 #6
            n = 8
            da = 2 * math.pi / n
            x, y = projected
            x, y = int(x), int(y)
            for i in range(n + 1):
                a = i * da
                dx = math.sin(a) * radius
                dy = math.cos(a) * radius
                if (i % 2) == 0:
                    bgl.glColor4f(0.0, 1.0, 0.0, 1.0)
                else:
                    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)
                bgl.glVertex2i(x + int(dx), y + int(dy))
            bgl.glEnd()

            # Restore previous OpenGL settings
            gl_enable(bgl.GL_SMOOTH, smooth_prev)

@addon.PropertyGroup
class BookmarkLibraryIDBlock(PseudoIDBlockBase):
    # Somewhy instance members aren't seen in update()
    # callbacks... but class members are.
    _self_update = [0]
    _dont_rename = [False]

    data_name = "Bookmark Library"
    op_new = "scene.cursor_3d_new_bookmark_library"
    op_delete = "scene.cursor_3d_delete_bookmark_library"
    icon = 'BOOKMARKS'

    collection, active, enum = PseudoIDBlockBase.create_props(BookmarkLibraryProp, "Bookmark Library")

    def on_item_select(self):
        library = self.get_item()
        library.bookmarks.update_enum()

@addon.Operator(idname="scene.cursor_3d_new_bookmark_library", label="New Library", description="Add a new bookmark library")
class NewCursor3DBookmarkLibrary(bpy.types.Operator):
    name = "Lib" | prop("Name of the new library", "Name")

    def execute(self, context):
        settings = find_settings()

        settings.libraries.add(name=self.name)

        return {'FINISHED'}

@addon.Operator(idname="scene.cursor_3d_delete_bookmark_library", label="Delete Library", description="Delete active bookmark library")
class DeleteCursor3DBookmarkLibrary:
    def execute(self, context):
        settings = find_settings()

        name = settings.libraries.active

        settings.libraries.remove(key=name)

        return {'FINISHED'}


# ===== MAIN PROPERTIES ===== #
# TODO: ~a bug? Somewhy tooltip shows "Cursor3DToolsSettings.foo"
# instead of "bpy.types.Screen.cursor_3d_tools_settings.foo"
@addon.PropertyGroup
class Cursor3DToolsSettings:
    transform_options = TransformExtraOptionsProp | prop()
    cursor_visible = True | prop("Show/hide cursor. When hidden, Blender continuously redraws itself (eats CPU like crazy, and becomes the less responsive the more complex scene you have)!", "Cursor visibility")
    draw_guides = True | prop("Display guides", "Guides")
    draw_snap_elements = True | prop("Display snap elements", "Snap elements")
    draw_N = True | prop("Display surface normal", "Surface normal")
    draw_T1 = True | prop("Display 1st surface tangential", "Surface 1st tangential")
    draw_T2 = True | prop("Display 2nd surface tangential", "Surface 2nd tangential")
    stick_to_obj = True | prop("Move cursor along with object it was snapped to", "Stick to objects")
    
    # HISTORY-RELATED
    history = CursorHistoryProp | prop()

    # BOOKMARK-RELATED
    libraries = BookmarkLibraryIDBlock | prop()
    show_bookmarks = True | prop("Show active bookmark in 3D view", "Show bookmarks")
    free_coord_precision = 4 | prop("Number of digits afer comma for displayed coordinate values", "Coord precision", min=0, max=10)
    
    # HERE THERE BE DRAGONS
    auto_register_keymaps = True | prop("Auto Register Keymaps", "Auto Register Keymaps")

@addon.PropertyGroup
class Cursor3DToolsSceneSettings:
    stick_obj_name = "" | prop("Name of the object to stick cursor to", "Stick-to-object name")
    stick_obj_pos = Vector() | prop()

# ===== CURSOR RUNTIME PROPERTIES ===== #
@addon.PropertyGroup
class CursorRuntimeSettings:
    current_monitor_id = 0 | prop()
    surface_pos = Vector() | prop()

class CursorDynamicSettings:
    local_matrix = Matrix()

    active_transform_operator = None

    csu = None

    active_scene_hash = 0

    @classmethod
    def recalc_csu(cls, context, event_value=None):
        scene_hash_changed = (cls.active_scene_hash != hash(context.scene))
        cls.active_scene_hash = hash(context.scene)

        # Don't recalc if mouse is over some UI panel!
        # (otherwise, this may lead to applying operator
        # (e.g. Subdivide) in Edit Mode, even if user
        # just wants to change some operator setting)
        clicked = (event_value in {'PRESS', 'RELEASE'}) and \
            (context.region.type == 'WINDOW')

        if clicked or scene_hash_changed:
            particles, cls.csu = gather_particles()
