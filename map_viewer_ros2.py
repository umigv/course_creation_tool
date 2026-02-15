#!/usr/bin/env python3
"""
ROS2 Humble interface for MapViewer.

Subscribes to:
  - /odom (nav_msgs/Odometry): Robot odometry

Publishes:
  - /occupancy_grid (nav_msgs/OccupancyGrid): Live occupancy grid from robot's perspective

Requires:
  pip install pygame numpy
  sudo apt install ros-humble-nav-msgs ros-humble-tf2-ros
"""

import math
import threading
import numpy as np
import pygame

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from nav_msgs.msg import Odometry, OccupancyGrid
from geometry_msgs.msg import Pose as ROSPose
from std_msgs.msg import Header

from map_viewer import MapViewer, Pose


def euler_from_quaternion(quat):
    """
    Convert quaternion to euler angles (roll, pitch, yaw).
    
    Args:
        quat: Quaternion as [x, y, z, w] or geometry_msgs/Quaternion
        
    Returns:
        tuple: (roll, pitch, yaw) in radians
    """
    # Handle both list/tuple and geometry_msgs.msg.Quaternion
    if hasattr(quat, 'x'):
        x, y, z, w = quat.x, quat.y, quat.z, quat.w
    else:
        x, y, z, w = quat
    
    # Roll (x-axis rotation)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    
    # Pitch (y-axis rotation)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)  # Use 90 degrees if out of range
    else:
        pitch = math.asin(sinp)
    
    # Yaw (z-axis rotation)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    
    return roll, pitch, yaw


class MapViewerROS2(Node):
    """
    ROS2 node that visualizes a map and publishes occupancy grids based on odometry.
    """
    
    def __init__(self, map_file, 
                 robot_width=0.4, robot_height=0.5,
                 grid_offset_x=0.2, grid_offset_y=0.0,
                 grid_resolution=0.05, grid_width=2.0, grid_height=2.0,
                 publish_rate=10.0):
        """
        Initialize the ROS2 map viewer node.
        
        Args:
            map_file: Path to JSON map file
            robot_width: Robot width in meters
            robot_height: Robot height/length in meters
            grid_offset_x: Grid X offset from robot center (meters)
            grid_offset_y: Grid Y offset from robot center (meters)
            grid_resolution: Grid cell size (meters)
            grid_width: Grid width (meters)
            grid_height: Grid height (meters)
            publish_rate: Occupancy grid publish rate (Hz)
        """
        super().__init__('map_viewer_ros2')
        
        # Declare parameters
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter('grid_topic', '/inflated_occupancy_grid')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('robot_frame', 'base_link')
        
        # Get parameters
        odom_topic = self.get_parameter('odom_topic').value
        grid_topic = self.get_parameter('grid_topic').value
        self.map_frame = self.get_parameter('map_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value
        
        self.get_logger().info(f"Loading map from {map_file}")
        
        # Create map viewer (pygame window)
        self.viewer = MapViewer(
            map_file,
            width=1200,
            height=800,
            robot_width=robot_width,
            robot_height=robot_height,
            grid_offset_x=grid_offset_x,
            grid_offset_y=grid_offset_y,
            grid_resolution=grid_resolution,
            grid_width=grid_width,
            grid_height=grid_height
        )
        
        # Store grid parameters
        self.grid_resolution = grid_resolution
        self.grid_width = grid_width
        self.grid_height = grid_height
        
        # QoS profile for odometry (typically best effort)
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth=10
        )
        
        # Subscribe to odometry
        self.odom_sub = self.create_subscription(
            Odometry,
            odom_topic,
            self.odom_callback,
            qos_profile
        )
        
        # Publisher for occupancy grid
        self.grid_pub = self.create_publisher(
            OccupancyGrid,
            grid_topic,
            10
        )
        
        # Timer for publishing occupancy grid
        publish_period = 1.0 / publish_rate
        self.grid_timer = self.create_timer(publish_period, self.publish_grid)
        
        # Thread-safe lock for pose updates
        self.pose_lock = threading.Lock()
        
        self.get_logger().info(f"Subscribed to: {odom_topic}")
        self.get_logger().info(f"Publishing to: {grid_topic} at {publish_rate} Hz")
        self.get_logger().info(f"Grid: {grid_width}m x {grid_height}m, resolution: {grid_resolution}m")
        self.get_logger().info("Map viewer initialized. Use pygame window controls to navigate.")
    
    def odom_callback(self, msg):
        """
        Handle incoming odometry messages and update robot pose.
        
        Args:
            msg: nav_msgs/Odometry message
        """
        # Extract position
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        
        # Extract orientation (convert quaternion to yaw)
        _, _, yaw = euler_from_quaternion(msg.pose.pose.orientation)
        
        # Update viewer pose (thread-safe)
        with self.pose_lock:
            self.viewer.set_robot_pose(Pose(x=x, y=y, theta=yaw))
    
    def publish_grid(self):
        """
        Publish the current occupancy grid based on robot pose.
        """
        # Get occupancy grid from viewer (thread-safe)
        with self.pose_lock:
            grid_data = self.viewer.get_occupancy_grid()
            robot_pose = self.viewer.robot_pose
        
        # Create OccupancyGrid message
        grid_msg = OccupancyGrid()
        
        # Header
        grid_msg.header = Header()
        grid_msg.header.stamp = self.get_clock().now().to_msg()
        grid_msg.header.frame_id = self.robot_frame
        
        # Grid metadata
        grid_msg.info.resolution = self.grid_resolution
        grid_msg.info.width = self.viewer.grid_cells_x
        grid_msg.info.height = self.viewer.grid_cells_y
        
        # Grid origin (in robot frame, this is the offset)
        # The grid origin is at the bottom-left corner of the grid
        # Our grid offset defines where the grid starts relative to robot center
        grid_msg.info.origin.position.x = self.viewer.grid_offset_x
        grid_msg.info.origin.position.y = self.viewer.grid_offset_y
        grid_msg.info.origin.position.z = 0.0
        grid_msg.info.origin.orientation.w = 1.0
        
        # Convert grid data to ROS format
        # ROS OccupancyGrid: -1 (unknown), 0-100 (probability)
        # Our grid: 0 (free), 100 (occupied)
        # Flatten in row-major order (ROS standard)
        grid_msg.data = grid_data.flatten().tolist()
        
        # Publish
        self.grid_pub.publish(grid_msg)
    
    def run(self):
        """
        Run the viewer with integrated ROS2 spinning.
        Pygame runs in the main thread, ROS2 spins in background.
        """
        # Create a background thread for ROS2 spinning
        def spin_thread():
            rclpy.spin(self)
        
        ros_thread = threading.Thread(target=spin_thread, daemon=True)
        ros_thread.start()
        
        self.get_logger().info("Starting pygame viewer (close window to exit)")
        
        # Run pygame main loop in main thread
        try:
            while rclpy.ok():
                self.viewer.clock.tick(60)
                if not self.viewer.handle_events():
                    break
                
                # Draw with thread-safe pose access
                with self.pose_lock:
                    self.viewer.draw()
        
        except KeyboardInterrupt:
            self.get_logger().info("Keyboard interrupt received")
        
        finally:
            pygame.quit()
            self.destroy_node()


def main(args=None):
    """Main entry point"""
    import argparse
    import sys
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="ROS2 Map Viewer")
    parser.add_argument("map_file", help="JSON map file from map_editor.py")
    parser.add_argument("--robot-width", type=float, default=0.4,
                       help="Robot width in meters (default: 0.4)")
    parser.add_argument("--robot-height", type=float, default=0.5,
                       help="Robot height/length in meters (default: 0.5)")
    parser.add_argument("--grid-offset-x", type=float, default=0.60,
                       help="Grid X offset from robot center (default: 0.2)")
    parser.add_argument("--grid-offset-y", type=float, default=-5/2,
                       help="Grid Y offset from robot center (default: 0.0)")
    parser.add_argument("--grid-resolution", type=float, default=0.05,
                       help="Grid resolution in meters (default: 0.05)")
    parser.add_argument("--grid-width", type=float, default=5.0,
                       help="Grid width in meters (default: 5.0)")
    parser.add_argument("--grid-height", type=float, default=5.0,
                       help="Grid height in meters (default: 5.0)")
    parser.add_argument("--publish-rate", type=float, default=10.0,
                       help="Occupancy grid publish rate in Hz (default: 10.0)")
    
    # Filter out ROS arguments
    filtered_args = []
    for arg in sys.argv[1:]:
        if not arg.startswith('__'):
            filtered_args.append(arg)
    
    parsed_args = parser.parse_args(filtered_args)
    
    # Initialize ROS2
    rclpy.init(args=args)
    
    try:
        # Create and run node
        node = MapViewerROS2(
            parsed_args.map_file,
            robot_width=parsed_args.robot_width,
            robot_height=parsed_args.robot_height,
            grid_offset_x=parsed_args.grid_offset_x,
            grid_offset_y=parsed_args.grid_offset_y,
            grid_resolution=parsed_args.grid_resolution,
            grid_width=parsed_args.grid_width,
            grid_height=parsed_args.grid_height,
            publish_rate=parsed_args.publish_rate
        )
        
        node.run()
    
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()