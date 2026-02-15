#!/usr/bin/env python3
"""
Example usage of MapViewer showing how to:
- Load a map
- Set robot pose dynamically
- Get occupancy grid data
- Update visualization in real-time
"""

import math
import numpy as np
from map_viewer import MapViewer, Pose


def demo_static_pose(map_file):
    """Simple example with static robot pose"""
    viewer = MapViewer(
        map_file,
        robot_width=0.4,
        robot_height=0.5,
        grid_offset_x=0.2,
        grid_offset_y=0.0,
        grid_resolution=0.05,
        grid_width=2.0,
        grid_height=2.0
    )
    
    # Set robot pose
    viewer.set_robot_pose(Pose(x=1.0, y=0.5, theta=math.pi/4))
    
    # Get occupancy grid
    grid = viewer.get_occupancy_grid()
    print(f"Occupancy grid shape: {grid.shape}")
    print(f"Occupied cells: {np.count_nonzero(grid)} / {grid.size}")
    
    viewer.run()


def demo_animated_pose(map_file):
    """Example with animated robot pose"""
    import pygame
    
    viewer = MapViewer(
        map_file,
        robot_width=0.4,
        robot_height=0.5,
        grid_offset_x=0.2,
        grid_offset_y=0.0,
        grid_resolution=0.05,
        grid_width=2.0,
        grid_height=2.0
    )
    
    # Animation parameters
    t = 0
    radius = 2.0
    
    while True:
        viewer.clock.tick(60)
        if not viewer.handle_events():
            break
        
        # Update robot pose in a circle
        t += 0.02
        x = radius * math.cos(t)
        y = radius * math.sin(t)
        theta = t + math.pi/2  # Face tangent to circle
        
        viewer.set_robot_pose(Pose(x=x, y=y, theta=theta))
        
        # Optionally get occupancy grid each frame
        grid = viewer.get_occupancy_grid()
        
        viewer.draw()
    
    pygame.quit()


def demo_grid_analysis(map_file):
    """Example showing how to analyze the occupancy grid"""
    viewer = MapViewer(
        map_file,
        robot_width=0.4,
        robot_height=0.5,
        grid_offset_x=0.2,
        grid_offset_y=0.0,
        grid_resolution=0.05,
        grid_width=3.0,
        grid_height=3.0
    )
    
    # Test multiple poses
    test_poses = [
        Pose(0, 0, 0),
        Pose(1, 1, math.pi/4),
        Pose(-1, 2, -math.pi/2),
    ]
    
    for i, pose in enumerate(test_poses):
        viewer.set_robot_pose(pose)
        grid = viewer.get_occupancy_grid()
        
        print(f"\nPose {i+1}: x={pose.x:.2f}, y={pose.y:.2f}, θ={math.degrees(pose.theta):.1f}°")
        print(f"  Grid shape: {grid.shape}")
        print(f"  Occupied cells: {np.count_nonzero(grid)}")
        print(f"  Free cells: {np.count_nonzero(grid == 0)}")
        print(f"  Occupancy %: {100 * np.count_nonzero(grid) / grid.size:.1f}%")
    
    # Show the last pose
    viewer.run()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python example_usage.py <map_file.json> [mode]")
        print("  mode: static (default), animated, or analysis")
        sys.exit(1)
    
    map_file = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "static"
    
    if mode == "static":
        demo_static_pose(map_file)
    elif mode == "animated":
        demo_animated_pose(map_file)
    elif mode == "analysis":
        demo_grid_analysis(map_file)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)