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

import bgl

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
    bgl.GL_DEPTH_FUNC:(bgl.GL_INT, 1),
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

def gl_matrix_to_buffer(m, dtype=bgl.GL_FLOAT):
    tempMat = [m[i][j] for i in range(4) for j in range(4)]
    return bgl.Buffer(dtype, 16, tempMat)

