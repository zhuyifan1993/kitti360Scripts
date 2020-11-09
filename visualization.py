import numpy as np
import os
import open3d as o3d


def normalize_data(input_data):
    """

    Args:
        input_data: raw data, size=(point_samples, point_dimension)

    Returns:
        output_data: normalized data between [-0.5, 0.5]

    """

    pts = input_data
    size = pts.max(axis=0) - pts.min(axis=0)
    pts = pts / size.max()
    pts -= (pts.max(axis=0) + pts.min(axis=0)) / 2
    output_data = pts

    return output_data


DATA_PATH = 'data_3d_car_pointcloud/2013_05_28_drive_0000_sync/000002_000385'

data = np.load(os.path.join(DATA_PATH, '1_canonical.npy'))
data = normalize_data(data)
np.savetxt('scene1.txt', data)
pcd = o3d.io.read_point_cloud('scene1.txt', format='xyz')
aabb = pcd.get_axis_aligned_bounding_box()

print(pcd)
o3d.io.write_point_cloud('1.ply', pcd)
o3d.visualization.draw_geometries([pcd, aabb])
