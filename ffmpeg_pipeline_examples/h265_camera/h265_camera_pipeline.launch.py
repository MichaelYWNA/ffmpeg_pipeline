"""
Forward a native H.265/HEVC camera stream to a ROS 2 topic as CompressedImage.

Same wiring as h264_camera_pipeline.launch.py; only the hardware description differs
(input_format: hevc, 1920x1080@30). Added in this fork as a second worked example of a
pass-through pipeline that does not re-encode.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution

from launch_ros.actions import Node, PushRosNamespace
from launch_ros.descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """
    Build the launch description for the HEVC camera pass-through pipeline.

    The pipeline is: FFmpegInput (v4l2, hevc) -> CompressedImageBroadcaster, plus an
    image_view node which decodes the stream through the ffmpeg image transport.
    """
    ##################
    # Launch Arguments
    ##################

    # namespace
    declare_namespace = DeclareLaunchArgument(
        'namespace',
        default_value='',
        description='Namespace for the nodes, topics, and parameters'
    )
    namespace = LaunchConfiguration('namespace')

    #######
    # Nodes
    #######

    # Publisher node for the hardware_description topic.
    hw_description_content = Command(
        [
            PathJoinSubstitution([FindExecutable(name='xacro')]),
            ' ',
            PathJoinSubstitution(
                [
                    FindPackageShare('ffmpeg_pipeline_examples'),
                    'h265_camera',
                    'hardware_description.urdf.xacro',
                ]
            ),
        ]
    )
    hw_description_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='hardware_description_publisher',
        parameters=[{'robot_description': ParameterValue(hw_description_content, value_type=str)}],
        remappings=[('robot_description', 'hardware_description')],
        output='both',
    )

    # The ros2_control_node which loads FFmpegInput and the broadcaster.
    ffmpeg_controllers = PathJoinSubstitution(
        [
            FindPackageShare('ffmpeg_pipeline_examples'),
            'h265_camera',
            'controllers.yaml',
        ]
    )
    ros2_control_node = Node(
        package='controller_manager',
        executable='ros2_control_node',
        name='ros2_control_node',
        parameters=[ffmpeg_controllers],
        remappings=[('robot_description', 'hardware_description')],
        output='both',
    )

    # The controller spawner.
    controller_spawner = Node(
        package='controller_manager',
        executable='spawner',
        name='controller_spawner',
        arguments=[
            '--controller-manager',
            'ros2_control_node',
            'compressed_image_broadcaster',
            ],
        output='both',
    )

    # Image viewer which decodes the forwarded HEVC stream via the ffmpeg image transport.
    image_view_node = Node(
        package='image_view',
        executable='image_view',
        name='image_view',
        parameters=[{
            'image_transport': 'ffmpeg',
            'compressed_image_broadcaster.image.ffmpeg': {
                'hw_type_name': 'auto',  # 'cuda', 'vaapi', 'vulkan', ...
            },
        }],
        remappings=[('image', 'compressed_image_broadcaster/image')],
        output='both',
    )

    ####################
    # Launch Description
    ####################

    return LaunchDescription(
        [
            declare_namespace,
            GroupAction(
                [
                    PushRosNamespace(namespace),
                    hw_description_publisher,
                    ros2_control_node,
                    controller_spawner,
                    image_view_node,
                ]
            ),
        ]
    )
