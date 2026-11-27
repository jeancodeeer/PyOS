# OpenGL for SnakeyOS: OpenGL 1.x drawn by software, with the names and the
# way of calling of PyOpenGL, so programs written for PyOpenGL + pygame
# run here as they are.
#
#   OpenGL.GL     the OpenGL functions (glBegin, glVertex3f, glRotatef...)
#   OpenGL.GLU    cameras and round shapes (gluPerspective, gluSphere...)
#   OpenGL.GLUT   windows and solid shapes, the GLUT way (glutMainLoop...)
#
# How it works: OpenGL/context.py keeps the state and turns vertices into
# triangles on the screen; OpenGL/raster.py fills their pixels (viper).
version = "1.5 (SnakeyOS, software)"
ERROR_CHECKING = True
