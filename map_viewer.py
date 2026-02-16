#!/usr/bin/env python3
"""
Map Viewer — read-only viewer for maps created by map_editor.py
Displays obstacles and allows visualizing robot pose with occupancy grid.

Requires:  pip install pygame numpy

Controls:
  LMB drag        -> pan camera
  Scroll wheel    -> zoom in / out
  R               -> reset view to origin
"""

import math
import json
import sys
import pygame
import numpy as np
from map_renderer_base import MapRendererBase, BG_COLOR, DEFAULT_PPM
from dpi_utils import setup_pygame_dpi_awareness, get_system_scale_factor


# ── Additional Colors for Viewer ──────────────────────────────────────────────
ROBOT_COLOR    = (72, 136, 255)
ROBOT_DIR_COLOR = (240, 65, 65)
OCCUPANCY_GRID_COLOR = (60, 200, 100, 80)  # Translucent green


class Pose:
    """Simple pose class with x, y (in meters) and theta (in radians)"""
    def __init__(self, x=0.0, y=0.0, theta=0.0):
        self.x = x
        self.y = y
        self.theta = theta


class MapViewer(MapRendererBase):
    """
    Read-only map viewer for displaying robot pose and occupancy grid
    on maps created by map_editor.py
    """
    
    def __init__(self, map_file, width=1200, height=800,
                 robot_width=0.4, robot_height=0.5,
                 grid_offset_x=0.2, grid_offset_y=0.0,
                 grid_resolution=0.05, grid_width=2.0, grid_height=2.0):
        """
        Initialize the map viewer.
        
        Args:
            map_file: Path to JSON map file from map_editor.py
            width, height: Window dimensions in pixels (logical, before scaling)
            robot_width: Robot width in meters
            robot_height: Robot height in meters (length)
            grid_offset_x: X offset from robot center to grid origin (meters)
            grid_offset_y: Y offset from robot center to grid origin (meters)
            grid_resolution: Size of each occupancy grid cell (meters)
            grid_width: Width of occupancy grid (meters)
            grid_height: Height of occupancy grid (meters)
        """
        # Setup DPI awareness before pygame.init()
        scale_factor = setup_pygame_dpi_awareness()
        pygame.init()
        
        # Apply scale factor to window size
        self.scale_factor = scale_factor
        self.W = int(width * scale_factor)
        self.H = int(height * scale_factor)
        
        screen = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        pygame.display.set_caption("Map Viewer")
        
        # Initialize base class with scale factor
        super().__init__(screen, DEFAULT_PPM, scale_factor)
        
        self.clock = pygame.time.Clock()
        
        # Create font with scaled size
        self.font = pygame.font.SysFont("monospace", self.dims.font_size)
        
        # Load map
        self._load_map(map_file)
        
        # Robot parameters
        self.robot_width = robot_width
        self.robot_height = robot_height
        self.robot_pose = Pose()  # Default at origin
        
        # Occupancy grid parameters
        self.grid_offset_x = grid_offset_x
        self.grid_offset_y = grid_offset_y
        self.grid_resolution = grid_resolution
        self.grid_width = grid_width
        self.grid_height = grid_height
        
        # Calculate grid dimensions in cells
        self.grid_cells_x = int(self.grid_width / self.grid_resolution)
        self.grid_cells_y = int(self.grid_height / self.grid_resolution)
        
        # UI Scale slider
        self.show_scale_slider = True
        self.scale_slider_dragging = False
        self.scale_slider_preview = None  # Preview scale while dragging
        self.base_scale_factor = scale_factor  # Store original detected scale
        self._update_font()
    
    def _update_font(self):
        """Recreate font with current scale"""
        self.font = pygame.font.SysFont("monospace", self.dims.font_size)
        
    def _load_map(self, filename):
        """Load obstacles from JSON file"""
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            self.obstacles = set(tuple(c) for c in data.get('obstacles', []))
            print(f"Loaded {len(self.obstacles)} obstacles from {filename}")
        except Exception as e:
            print(f"Error loading map: {e}")
            self.obstacles = set()
    
    def set_robot_pose(self, pose):
        """
        Set the robot pose.
        
        Args:
            pose: Pose object with x, y (meters) and theta (radians)
        """
        self.robot_pose = pose
    
    def get_occupancy_grid(self):
        """
        Generate and return the occupancy grid as a 2D numpy array.
        
        Returns:
            numpy array of shape (grid_cells_y, grid_cells_x) where:
            0 = free space
            100 = occupied
        """
        grid = np.zeros((self.grid_cells_y, self.grid_cells_x), dtype=np.int8)
        
        # Transform grid origin to world frame
        cos_t = math.cos(self.robot_pose.theta)
        sin_t = math.sin(self.robot_pose.theta)
        
        # Grid origin in world coordinates
        grid_world_x = self.robot_pose.x + cos_t * self.grid_offset_x - sin_t * self.grid_offset_y
        grid_world_y = self.robot_pose.y + sin_t * self.grid_offset_x + cos_t * self.grid_offset_y
        
        # Check each grid cell
        for gy in range(self.grid_cells_y):
            for gx in range(self.grid_cells_x):
                # Grid cell center in grid frame
                cell_grid_x = (gx + 0.5) * self.grid_resolution
                cell_grid_y = (gy + 0.5) * self.grid_resolution
                
                # Transform to world frame
                cell_world_x = grid_world_x + cos_t * cell_grid_x - sin_t * cell_grid_y
                cell_world_y = grid_world_y + sin_t * cell_grid_x + cos_t * cell_grid_y
                
                # Convert to map cell coordinates (row, col)
                map_cell_row = int(round(cell_world_y / 0.05))  # CELL_M from base
                map_cell_col = int(round(cell_world_x / 0.05))
                
                # Check if this map cell has an obstacle
                if (map_cell_row, map_cell_col) in self.obstacles:
                    grid[gy, gx] = 100
        
        return grid
    
    def draw(self):
        """Render the map, robot, and occupancy grid"""
        self.screen.fill(BG_COLOR)
        
        # Draw obstacles
        self.draw_obstacles()
        
        # Draw robot and occupancy grid
        self._draw_robot()
        self._draw_occupancy_grid()
        
        # Draw grid on top of everything
        self.draw_grid()
        
        # Draw info overlay
        self._draw_info()
        
        # Draw scale slider
        self._draw_scale_slider()
        
        pygame.display.flip()
    
    def _draw_robot(self):
        """Draw the robot as a rectangle with direction indicator"""
        # Robot corners in robot frame
        # Robot length (height) is along X axis, width is along Y axis
        # So theta = 0 points east (positive X)
        hw = self.robot_width / 2
        hh = self.robot_height / 2
        corners_local = [
            (-hh, -hw), (hh, -hw), (hh, hw), (-hh, hw)
        ]
        
        # Transform to world frame
        cos_t = math.cos(self.robot_pose.theta)
        sin_t = math.sin(self.robot_pose.theta)
        
        corners_world = []
        for lx, ly in corners_local:
            wx = self.robot_pose.x + cos_t * lx - sin_t * ly
            wy = self.robot_pose.y + sin_t * lx + cos_t * ly
            corners_world.append(self.world_to_screen(wx, wy))
        
        # Draw robot body
        pygame.draw.polygon(self.screen, ROBOT_COLOR, corners_world)
        pygame.draw.polygon(self.screen, (0, 0, 0), corners_world, self.dims.robot_outline_width)
        
        # Draw direction indicator (front of robot) - points in +X direction at theta = 0
        front_local_x = hh
        front_local_y = 0
        front_world_x = self.robot_pose.x + cos_t * front_local_x - sin_t * front_local_y
        front_world_y = self.robot_pose.y + sin_t * front_local_x + cos_t * front_local_y
        
        center_screen = self.world_to_screen(self.robot_pose.x, self.robot_pose.y)
        front_screen = self.world_to_screen(front_world_x, front_world_y)
        
        pygame.draw.line(self.screen, ROBOT_DIR_COLOR, center_screen, front_screen, 
                        self.dims.robot_direction_width)
        pygame.draw.circle(self.screen, ROBOT_DIR_COLOR, 
                          (int(front_screen[0]), int(front_screen[1])), 
                          self.dims.robot_direction_circle_radius)
    
    def _draw_occupancy_grid(self):
        """Draw the occupancy grid as a translucent box"""
        # Grid corners in grid frame
        corners_grid = [
            (0, 0),
            (self.grid_width, 0),
            (self.grid_width, self.grid_height),
            (0, self.grid_height)
        ]
        
        # Transform to world frame
        cos_t = math.cos(self.robot_pose.theta)
        sin_t = math.sin(self.robot_pose.theta)
        
        # Grid origin in world frame
        grid_world_x = self.robot_pose.x + cos_t * self.grid_offset_x - sin_t * self.grid_offset_y
        grid_world_y = self.robot_pose.y + sin_t * self.grid_offset_x + cos_t * self.grid_offset_y
        
        corners_world = []
        for gx, gy in corners_grid:
            wx = grid_world_x + cos_t * gx - sin_t * gy
            wy = grid_world_y + sin_t * gx + cos_t * gy
            corners_world.append(self.world_to_screen(wx, wy))
        
        # Create translucent surface
        surf = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        pygame.draw.polygon(surf, OCCUPANCY_GRID_COLOR, corners_world)
        pygame.draw.polygon(surf, (60, 200, 100, 180), corners_world, 
                          self.dims.occupancy_grid_outline_width)
        self.screen.blit(surf, (0, 0))
    
    def _draw_info(self):
        """Draw information overlay"""
        _, block = self._lod()
        lines = [
            f"Robot Pose: ({self.robot_pose.x:.2f}, {self.robot_pose.y:.2f}) θ={math.degrees(self.robot_pose.theta):.1f}°",
            f"Robot Size: {self.robot_width:.2f}m × {self.robot_height:.2f}m",
            f"Grid Size: {self.grid_width:.2f}m × {self.grid_height:.2f}m",
            f"Grid Resolution: {self.grid_resolution*100:.1f}cm/cell ({self.grid_cells_x}×{self.grid_cells_y} cells)",
            f"Grid Offset: ({self.grid_offset_x:.2f}, {self.grid_offset_y:.2f})",
            f"Zoom: {self.ppm:.1f} px/m | LOD: {block}x{block} cells merged",
            f"Obstacles: {len(self.obstacles):,}",
        ]
        
        margin = self.dims.info_margin
        padding_x = self.dims.info_padding_x
        padding_y = self.dims.info_padding_y
        line_spacing = self.dims.info_line_spacing
        
        y = margin
        for line in lines:
            surf = self.font.render(line, True, (0, 0, 0))
            bg = pygame.Surface((surf.get_width() + padding_x, surf.get_height() + padding_y))
            bg.fill((255, 255, 255))
            bg.set_alpha(200)
            self.screen.blit(bg, (margin, y - padding_y // 2))
            self.screen.blit(surf, (margin + padding_x // 2, y))
            y += surf.get_height() + line_spacing
    
    def _draw_scale_slider(self):
        """Draw UI scale slider at bottom of screen"""
        if not self.show_scale_slider:
            return
        
        # Use current scale for layout, but base scale for positioning stability
        ui_scale = self.dims.scale
        
        # Slider dimensions - use current scale
        slider_w = int(200 * ui_scale)
        slider_h = int(30 * ui_scale)
        slider_x = self.W - slider_w - int(20 * ui_scale)
        slider_y = self.H - slider_h - int(20 * ui_scale)
        
        # Background
        bg_padding = int(10 * ui_scale)
        bg_top_pad = int(25 * ui_scale)
        bg_bottom_pad = int(15 * ui_scale)
        bg = pygame.Surface((slider_w + bg_padding * 2, slider_h + bg_top_pad + bg_bottom_pad), pygame.SRCALPHA)
        bg.fill((255, 255, 255, 200))
        self.screen.blit(bg, (slider_x - bg_padding, slider_y - bg_top_pad))
        
        # Label - show preview scale while dragging, otherwise current scale
        display_scale = self.scale_slider_preview if self.scale_slider_preview is not None else self.dims.scale
        label_font = pygame.font.SysFont("monospace", int(11 * ui_scale))
        label = label_font.render(f"UI Scale: {display_scale:.2f}x", True, (0, 0, 0))
        self.screen.blit(label, (slider_x, slider_y - int(18 * ui_scale)))
        
        # Slider track
        track_y_offset = int(10 * ui_scale)
        track_h = int(4 * ui_scale)
        track_rect = pygame.Rect(slider_x, slider_y + track_y_offset, slider_w, track_h)
        pygame.draw.rect(self.screen, (180, 180, 180), track_rect, border_radius=2)
        
        # Slider thumb position (0.5x to 3.0x) - use preview or current
        scale_range = 3.0 - 0.5
        normalized = (display_scale - 0.5) / scale_range
        thumb_x = slider_x + int(normalized * slider_w)
        thumb_y = slider_y + track_y_offset + track_h // 2
        thumb_radius = int(8 * ui_scale)
        
        # Thumb - different color when dragging
        thumb_color = (100, 150, 255) if self.scale_slider_dragging else (72, 136, 255)
        pygame.draw.circle(self.screen, thumb_color, (thumb_x, thumb_y), thumb_radius)
        pygame.draw.circle(self.screen, (255, 255, 255), (thumb_x, thumb_y), thumb_radius - max(1, int(2 * ui_scale)))
        
        return pygame.Rect(slider_x, slider_y, slider_w, slider_h)
    
    def _get_slider_rect(self):
        """Get the slider interaction rect"""
        if not self.show_scale_slider:
            return None
        
        ui_scale = self.dims.scale
        slider_w = int(200 * ui_scale)
        slider_h = int(30 * ui_scale)
        slider_x = self.W - slider_w - int(20 * ui_scale)
        slider_y = self.H - slider_h - int(20 * ui_scale)
        
        return pygame.Rect(slider_x, slider_y, slider_w, slider_h)
    
    def _update_scale_from_mouse(self, mx):
        """Update scale preview based on mouse x position"""
        slider_rect = self._get_slider_rect()
        if not slider_rect:
            return
        
        # Calculate new scale (0.5x to 3.0x)
        normalized = (mx - slider_rect.x) / slider_rect.w
        normalized = max(0.0, min(1.0, normalized))
        new_scale = 0.5 + normalized * (3.0 - 0.5)
        
        # Store preview scale (don't apply until mouse up)
        self.scale_slider_preview = new_scale
    
    def _apply_scale_change(self):
        """Apply the previewed scale change"""
        if self.scale_slider_preview is None:
            return
        
        # Update scale
        self.dims.scale = self.scale_slider_preview
        self.scale_slider_preview = None
        self._update_font()
    
    def handle_events(self):
        """Handle pygame events"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            elif event.type == pygame.VIDEORESIZE:
                self.W, self.H = event.w, event.h
            
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                elif event.key == pygame.K_r:
                    self.reset_view()
                elif event.key == pygame.K_u:
                    # Toggle UI scale slider
                    self.show_scale_slider = not self.show_scale_slider
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # LMB
                    # Check if clicking on slider
                    slider_rect = self._get_slider_rect()
                    if slider_rect and slider_rect.collidepoint(event.pos):
                        self.scale_slider_dragging = True
                        self._update_scale_from_mouse(event.pos[0])
                    else:
                        # Start panning
                        self.start_pan(event.pos)
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:  # LMB
                    # Apply scale change if slider was being dragged
                    if self.scale_slider_dragging:
                        self._apply_scale_change()
                    self.scale_slider_dragging = False
                    self.stop_pan()
            
            elif event.type == pygame.MOUSEMOTION:
                if self.scale_slider_dragging:
                    self._update_scale_from_mouse(event.pos[0])
                else:
                    self.update_pan(event.pos)
            
            elif event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                self.zoom(event.y, mx, my)
        
        return True
    
    def run(self):
        """Main event loop"""
        while True:
            self.clock.tick(60)
            if not self.handle_events():
                break
            self.draw()
        pygame.quit()
        sys.exit(0)


# ── Example usage ──────────────────────────────────────────────────────────────
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Map viewer with robot pose")
    parser.add_argument("map_file", help="JSON map file from map_editor.py")
    parser.add_argument("--robot-width", type=float, default=0.4,
                       help="Robot width in meters (default: 0.4)")
    parser.add_argument("--robot-height", type=float, default=0.5,
                       help="Robot height/length in meters (default: 0.5)")
    parser.add_argument("--grid-offset-x", type=float, default=0.2,
                       help="Grid X offset from robot center (default: 0.2)")
    parser.add_argument("--grid-offset-y", type=float, default=0.0,
                       help="Grid Y offset from robot center (default: 0.0)")
    parser.add_argument("--grid-resolution", type=float, default=0.05,
                       help="Grid resolution in meters (default: 0.05)")
    parser.add_argument("--grid-width", type=float, default=2.0,
                       help="Grid width in meters (default: 2.0)")
    parser.add_argument("--grid-height", type=float, default=2.0,
                       help="Grid height in meters (default: 2.0)")
    
    args = parser.parse_args()
    
    viewer = MapViewer(
        args.map_file,
        robot_width=args.robot_width,
        robot_height=args.robot_height,
        grid_offset_x=args.grid_offset_x,
        grid_offset_y=args.grid_offset_y,
        grid_resolution=args.grid_resolution,
        grid_width=args.grid_width,
        grid_height=args.grid_height
    )
    
    # Example: Set robot pose (you can modify this)
    viewer.set_robot_pose(Pose(x=1.0, y=0.5, theta=0.785))  # 45 degrees
    
    # Example: Get occupancy grid
    grid = viewer.get_occupancy_grid()
    print(f"Occupancy grid shape: {grid.shape}")
    print(f"Occupied cells: {np.count_nonzero(grid)} / {grid.size}")
    
    viewer.run()


if __name__ == "__main__":
    main()