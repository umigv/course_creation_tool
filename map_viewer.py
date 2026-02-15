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
        
        # Initialize base class
        super().__init__(screen, DEFAULT_PPM)
        
        self.clock = pygame.time.Clock()
        
        # Scale font size based on DPI
        font_size = max(11, int(13 * scale_factor))
        self.font = pygame.font.SysFont("monospace", font_size)
        
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
        pygame.draw.polygon(self.screen, (0, 0, 0), corners_world, 2)
        
        # Draw direction indicator (front of robot) - points in +X direction at theta = 0
        front_local_x = hh
        front_local_y = 0
        front_world_x = self.robot_pose.x + cos_t * front_local_x - sin_t * front_local_y
        front_world_y = self.robot_pose.y + sin_t * front_local_x + cos_t * front_local_y
        
        center_screen = self.world_to_screen(self.robot_pose.x, self.robot_pose.y)
        front_screen = self.world_to_screen(front_world_x, front_world_y)
        
        pygame.draw.line(self.screen, ROBOT_DIR_COLOR, center_screen, front_screen, 3)
        pygame.draw.circle(self.screen, ROBOT_DIR_COLOR, 
                          (int(front_screen[0]), int(front_screen[1])), 5)
    
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
        pygame.draw.polygon(surf, (60, 200, 100, 180), corners_world, 2)
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
        
        y = 10
        for line in lines:
            surf = self.font.render(line, True, (0, 0, 0))
            bg = pygame.Surface((surf.get_width() + 10, surf.get_height() + 4))
            bg.fill((255, 255, 255))
            bg.set_alpha(200)
            self.screen.blit(bg, (5, y - 2))
            self.screen.blit(surf, (10, y))
            y += surf.get_height() + 2
    
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
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # LMB starts panning
                    self.start_pan(event.pos)
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:  # LMB stops panning
                    self.stop_pan()
            
            elif event.type == pygame.MOUSEMOTION:
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