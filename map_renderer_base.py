#!/usr/bin/env python3
"""
Shared base class for map rendering with zoom/pan functionality.
Used by both map_editor.py and map_viewer.py to ensure consistency.
"""

import math
import pygame


# ── Palette ───────────────────────────────────────────────────────────────────
BG_COLOR       = (248, 248, 252)
GRID_MINOR     = (215, 215, 230)
GRID_MAJOR     = (165, 165, 190)
GRID_SUPER     = (120, 120, 155)
AXIS_COLOR     = (120, 120, 155)
OBSTACLE_COLOR = (42, 45, 68)


# ── Constants ──────────────────────────────────────────────────────────────────
CELL_M       = 0.05  # Each cell is 5cm
MIN_PPM      = 0.5
MAX_PPM      = 8000.0
DEFAULT_PPM  = 200.0
MIN_CELL_PX  = 4
MAJOR_EVERY  = 10
SUPER_EVERY  = 100


class MapRendererBase:
    """
    Base class for map rendering with camera controls.
    Handles coordinate transformations, zoom, pan, and grid/obstacle rendering.
    """
    
    def __init__(self, screen, initial_ppm=DEFAULT_PPM):
        """
        Initialize the map renderer.
        
        Args:
            screen: pygame Surface to render to
            initial_ppm: Initial pixels per meter zoom level
        """
        self.screen = screen
        
        # Camera state
        self.cam_x = 0.0  # Camera position in world coordinates (meters)
        self.cam_y = 0.0
        self.ppm = initial_ppm  # Pixels per meter (zoom level)
        
        # Panning state
        self.panning = False
        self.pan_start = (0, 0)
        self.pan_cam_orig = (0.0, 0.0)
        
        # Obstacles (shared state)
        self.obstacles = set()
    
    def _lod(self):
        """
        Calculate level-of-detail merging factor.
        Returns (level, block_size) where block_size is the number of cells to merge.
        """
        pixels_per_cell = self.ppm * CELL_M
        if pixels_per_cell >= MIN_CELL_PX:
            return 0, 1
        level = 0
        block = 1
        while pixels_per_cell < MIN_CELL_PX and block < 2048:
            block *= 2
            level += 1
            pixels_per_cell = self.ppm * CELL_M * block
        return level, block
    
    def world_to_screen(self, wx, wy):
        """
        Convert world coordinates (meters) to screen pixels.
        Note: Screen Y increases downward, so we negate world Y.
        
        Args:
            wx, wy: World coordinates in meters
            
        Returns:
            (sx, sy): Screen coordinates in pixels
        """
        W, H = self.screen.get_size()
        sx = (wx - self.cam_x) * self.ppm + W / 2
        sy = -(wy - self.cam_y) * self.ppm + H / 2  # Negate Y for screen coords
        return sx, sy
    
    def screen_to_world(self, sx, sy):
        """
        Convert screen pixels to world coordinates (meters).
        Note: Screen Y increases downward, so we negate when converting to world.
        
        Args:
            sx, sy: Screen coordinates in pixels
            
        Returns:
            (wx, wy): World coordinates in meters
        """
        W, H = self.screen.get_size()
        wx = (sx - W / 2) / self.ppm + self.cam_x
        wy = -(sy - H / 2) / self.ppm + self.cam_y  # Negate Y for world coords
        return wx, wy
    
    def zoom(self, delta, mx, my):
        """
        Zoom in/out around mouse position.
        
        Args:
            delta: Scroll direction (positive = zoom in, negative = zoom out)
            mx, my: Mouse position in screen coordinates
        """
        # Store world position under mouse before zoom
        wx, wy = self.screen_to_world(mx, my)
        
        # Apply zoom
        old_ppm = self.ppm
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.ppm = max(MIN_PPM, min(MAX_PPM, self.ppm * factor))
        
        # Adjust camera so world position stays under mouse
        if self.ppm != old_ppm:
            # After zoom, where would that world point appear on screen?
            sx_new, sy_new = self.world_to_screen(wx, wy)
            
            # Calculate how much it shifted
            dx_screen = sx_new - mx
            dy_screen = sy_new - my
            
            # Adjust camera to compensate
            self.cam_x += dx_screen / self.ppm
            self.cam_y += dy_screen / self.ppm
    
    def reset_view(self):
        """Reset camera to origin with default zoom"""
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.ppm = DEFAULT_PPM
    
    def start_pan(self, mouse_pos):
        """
        Begin panning operation.
        
        Args:
            mouse_pos: (x, y) mouse position when panning started
        """
        self.panning = True
        self.pan_start = mouse_pos
        self.pan_cam_orig = (self.cam_x, self.cam_y)
    
    def update_pan(self, mouse_pos):
        """
        Update camera position during pan.
        
        Args:
            mouse_pos: Current (x, y) mouse position
        """
        if self.panning:
            mx, my = mouse_pos
            dx = (mx - self.pan_start[0]) / self.ppm
            dy = (my - self.pan_start[1]) / self.ppm
            self.cam_x = self.pan_cam_orig[0] - dx
            self.cam_y = self.pan_cam_orig[1] + dy  # + because screen Y is inverted

    
    def stop_pan(self):
        """End panning operation"""
        self.panning = False
    
    def draw_grid(self):
        """Draw coordinate grid with axes"""
        W, H = self.screen.get_size()
        _, block = self._lod()
        
        # Calculate grid range - get all four corners and find true min/max
        tl_x, tl_y = self.screen_to_world(0, 0)
        tr_x, tr_y = self.screen_to_world(W, 0)
        bl_x, bl_y = self.screen_to_world(0, H)
        br_x, br_y = self.screen_to_world(W, H)
        
        x_min = min(tl_x, tr_x, bl_x, br_x)
        x_max = max(tl_x, tr_x, bl_x, br_x)
        y_min = min(tl_y, tr_y, bl_y, br_y)
        y_max = max(tl_y, tr_y, bl_y, br_y)
        
        grid_size = CELL_M * block
        start_x = math.floor(x_min / grid_size) * grid_size
        start_y = math.floor(y_min / grid_size) * grid_size
        
        # Vertical lines
        x = start_x
        while x <= x_max:
            sx, _ = self.world_to_screen(x, 0)
            cell_idx = int(round(x / CELL_M))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            pygame.draw.line(self.screen, color, (sx, 0), (sx, H), 1)
            x += grid_size
        
        # Horizontal lines
        y = start_y
        while y <= y_max:
            _, sy = self.world_to_screen(0, y)
            cell_idx = int(round(y / CELL_M))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            pygame.draw.line(self.screen, color, (0, sy), (W, sy), 1)
            y += grid_size
        
        # Draw axes
        x0, _ = self.world_to_screen(0, 0)
        _, y0 = self.world_to_screen(0, 0)
        pygame.draw.line(self.screen, AXIS_COLOR, (x0, 0), (x0, H), 2)
        pygame.draw.line(self.screen, AXIS_COLOR, (0, y0), (W, y0), 2)
    
    def draw_obstacles(self):
        """Draw obstacle cells with LOD merging"""
        _, block = self._lod()
        merged_cells = {}
        
        # Merge cells into blocks - obstacles stored as (row, col)
        for r, c in self.obstacles:
            br = (r // block) * block
            bc = (c // block) * block
            merged_cells[(br, bc)] = True
        
        cell_screen = CELL_M * block * self.ppm
        
        # Draw merged cells
        for (br, bc) in merged_cells:
            wx = bc * CELL_M
            wy = br * CELL_M
            sx, sy = self.world_to_screen(wx, wy)
            rect = pygame.Rect(sx, sy, cell_screen, cell_screen)
            pygame.draw.rect(self.screen, OBSTACLE_COLOR, rect)