#!/usr/bin/python
# -*- coding: utf-8 -*-


#################
## Import modules
#################
import sys
# walk directories
import glob
# access to OS functionality
import os
# call processes
import subprocess
# copy things
import copy
# numpy
import numpy as np
# opencv
import cv2
# open3d
import open3d
# from lineset import LineMesh
# matplotlib for colormaps
import matplotlib.cm
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
# scipy
from scipy import interpolate
# struct for reading binary ply files
import struct
# parse arguments
import argparse

try:
    import matplotlib.colors
    from PIL import PILLOW_VERSION
    from PIL import Image
except:
    pass

#################
## Helper classes
#################

# annotation helper
from kitti360scripts.helpers.annotation import Annotation3D, Annotation3DPly, global2local
from kitti360scripts.helpers.project import Camera
from kitti360scripts.helpers.labels import name2label, id2label, kittiId2label
from scipy.spatial.transform import Rotation as Rot


# the main class that parse fused point clouds
class Kitti360Viewer3D(object):

    # Constructor
    def __init__(self, seq=0, showStatic=True):

        # The sequence of the image we currently working on
        self.currentSequence = ""
        # Image extension
        self.imageExt = ".png"
        # Filenames of all images in current city
        self.images = []
        self.imagesCityFull = []
        # Ground truth type
        self.gtType = 'semantic'
        # Add contour to semantic map
        self.semanticCt = True
        # Add contour to instance map
        self.instanceCt = True
        # The object that is highlighted and its label. An object instance
        self.highlightObj = None
        self.highlightObjSparse = None
        self.highlightObjLabel = None
        # The current object the mouse points to. It's index in self.labels
        self.mouseObj = -1
        # The current object the mouse points to. It's index in self.labels
        self.mousePressObj = -1
        self.mouseSemanticId = -1
        self.mouseInstanceId = -1
        # show camera or not
        self.showCamera = False
        self.downSampleEvery = -1
        # show bbox wireframe or mesh
        self.showWireframe = False
        self.show3DInstanceOnly = True
        # show static or dynamic point clouds
        self.showStatic = showStatic
        # show visible point clouds only
        self.showVisibleOnly = False
        # colormap
        self.cmap = matplotlib.cm.get_cmap('Set1')
        self.cmap_length = 9

        if 'KITTI360_DATASET' in os.environ:
            kitti360Path = os.environ['KITTI360_DATASET']
        else:
            kitti360Path = os.path.join(os.path.dirname(
                os.path.realpath(__file__)), '..', '..')

        sequence = '2013_05_28_drive_%04d_sync' % seq
        self.label3DPcdPath = os.path.join(kitti360Path, 'data_3d_semantics')
        self.label3DBboxPath = os.path.join(kitti360Path, 'data_3d_bboxes')
        self.annotation3D = Annotation3D(self.label3DBboxPath, sequence)
        self.annotation3DPly = Annotation3DPly(self.label3DPcdPath, sequence)
        self.sequence = sequence

        self.pointClouds = {}
        self.Rz = np.eye(3)
        self.bboxes = []
        self.bboxes_window = []
        self.accumuData = []

    def getColor(self, idx):
        if idx == 0:
            return np.array([0, 0, 0])
        return np.asarray(self.cmap(idx % self.cmap_length)[:3]) * 255.

    def assignColor(self, globalIds, gtType='semantic'):
        if not isinstance(globalIds, (np.ndarray, np.generic)):
            globalIds = np.array(globalIds)[None]
        color = np.zeros((globalIds.size, 3))
        for uid in np.unique(globalIds):
            semanticId, instanceId = global2local(uid)
            if gtType == 'semantic':
                color[globalIds == uid] = id2label[semanticId].color
            elif instanceId > 0:
                color[globalIds == uid] = self.getColor(instanceId)
            else:
                color[globalIds == uid] = (96, 96, 96)  # stuff objects in instance mode
        color = color.astype(np.float) / 255.0
        return color

    def assignColorDynamic(self, timestamps):
        color = np.zeros((timestamps.size, 3))
        for uid in np.unique(timestamps):
            color[timestamps == uid] = self.getColor(uid)
        return color

    def getLabelFilename(self, currentFile):
        # Generate the filename of the label file
        filename = os.path.basename(currentFile)
        search = [lb for lb in self.label_images if filename in lb]
        if not search:
            return ""
        filename = os.path.normpath(search[0])
        return filename

    def getCamTrajectory(self):
        self.camLineSets = []
        self.camDistance = 0
        cam2world = np.loadtxt(self.cam2worldPath)
        cam2world = np.reshape(cam2world[:, 1:], (-1, 4, 4))
        T = cam2world[:, :3, 3]
        self.numFrames = T.shape[0]

        color = np.array([0.75, 0., 0.]).reshape((1, 3))
        radius = 1.5
        for i in range(T.shape[0] - 1):
            line_mesh = LineMesh(T[i:i + 2], [[0, 1]], color, radius=radius)
            self.camLineSets += line_mesh.cylinder_segments
            self.camDistance += np.linalg.norm(T[i + 1] - T[i])

    def loadWindow(self, pcdFile, colorType='instance', isLabeled=True, isDynamic=False):
        window = pcdFile.split('\\')[-2]

        print('Loading %s ' % pcdFile)

        # load ply data using open3d for visualization
        if window in self.pointClouds.keys():
            pcd = self.pointClouds[window]
        else:
            pcd = open3d.io.read_point_cloud(pcdFile)

        n_pts = np.asarray(pcd.points).shape[0]
        data = self.annotation3DPly.readBinaryPly(pcdFile, n_pts)

        if self.showVisibleOnly:
            ind = 8 if isLabeled else 6
            mask = np.logical_and(data[:, 6] == 26, data[:, ind])
            pcd = pcd.select_by_index(np.where(mask)[0])

            data = data[mask.astype(np.bool), :]
            self.accumuData.append(data)
        else:
            # color = data[:, 3:6]
            # mask = np.logical_and(np.mean(color, 1) == 128, np.std(color, 1) == 0)
            # mask = 1 - mask
            # data = data.select_by_index(np.where(mask)[0])

            mask = np.logical_not(data[:, 6] == 26)  # filter out car objects
            mask = 1 - mask
            pcd = pcd.select_by_index(np.where(mask)[0])

            data = data[mask.astype(np.bool), :]
            self.accumuData.append(data)

        # assign color
        # if colorType == 'semantic' or colorType == 'instance':
        #     globalIds = data[:, 7]
        #     if self.showVisibleOnly:
        #         globalIds = globalIds[np.where(isVisible)[0]]
        #
        #     ptsColor = self.assignColor(globalIds, colorType)
        #     data.colors = open3d.utility.Vector3dVector(ptsColor)
        # elif colorType == 'bbox':
        #     ptsColor = np.asarray(data.colors)
        #     data.colors = open3d.utility.Vector3dVector(ptsColor)
        # elif colorType != 'rgb':
        #     raise ValueError("Color type can only be 'rgb', 'bbox', 'semantic', 'instance'!")
        #
        # if self.downSampleEvery > 1:
        #     print(np.asarray(data.points).shape)
        #     data = data.uniform_down_sample(self.downSampleEvery)
        #     print(np.asarray(data.points).shape)
        return data

    def loadWindows(self, colorType='semantic'):
        pcdFolder = 'static' if self.showStatic else 'dynamic'
        pcdFileList = sorted(glob.glob(os.path.join(self.label3DPcdPath, self.sequence, pcdFolder, '*.ply')))

        if not len(pcdFileList):
            print('%s does not exist!!' % os.path.join(self.label3DPcdPath, self.sequence, '*', pcdName))
            return None

        for idx, pcdFile in enumerate(pcdFileList):
            window = pcdFile.split('\\')[-2]
            pcd = self.loadWindow(pcdFile, colorType)

            self.pointClouds[window] = pcd

    def loadBoundingBoxes(self):

        transformList = []
        bboxidList = []
        for globalId, v in self.annotation3D.objects.items():
            # skip dynamic objects
            if len(v) > 1:
                continue
            for obj in v.values():
                if str(obj) is not 'car':
                    continue
                lines = np.array(obj.lines)
                vertices = obj.vertices
                faces = obj.faces
                mesh = open3d.geometry.TriangleMesh()
                mesh.vertices = open3d.utility.Vector3dVector(obj.vertices)
                mesh.triangles = open3d.utility.Vector3iVector(obj.faces)
                color = self.assignColor(globalId, 'semantic')
                semanticId, instanceId = global2local(globalId)
                transformList.append(obj.transform)
                bboxidList.append(instanceId)
                mesh.paint_uniform_color(color.flatten())
                mesh.compute_vertex_normals()
                self.bboxes.append(mesh)
                self.bboxes_window.append([obj.start_frame, obj.end_frame])
        return transformList, bboxidList

    def loadBoundingBoxWireframes(self):

        self.lineSets = []

        for globalId, v in self.annotation3D.objects.items():
            # skip dynamic objects
            if len(v) > 1:
                continue
            for obj in v.values():
                lines = np.array(obj.lines)
                points = obj.vertices
                color = self.assignColor(0, 'semantic')
                semanticId, instanceId = global2local(globalId)
                if 'pole' in id2label[semanticId].name:
                    radius = 0.05
                else:
                    radius = 0.08
                color = np.tile(color, (lines.shape[0], 1))
                line_set = open3d.geometry.LineSet(
                    points=open3d.utility.Vector3dVector(points),
                    lines=open3d.utility.Vector2iVector(lines),
                )
                line_set.colors = open3d.utility.Vector3dVector(color)
                self.lineSets.append(line_set)

    def lookat(self, look_from, look_to, tmp=np.asarray([0, 0, 1])):
        forward = - look_from + look_to
        forward = forward / np.linalg.norm(forward)
        right = -np.cross(tmp, forward)
        up = np.cross(forward, right)

        camToWorld = np.zeros((4, 4))

        camToWorld[0, 0:3] = right
        camToWorld[1, 0:3] = up
        camToWorld[2, 0:3] = forward
        camToWorld[3, 0:3] = look_from
        camToWorld[3, 3] = 1

        return camToWorld


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--sequence', type=int, default=0,
                        help='The sequence to visualize')
    parser.add_argument('--mode', choices=['rgb', 'semantic', 'instance', 'bbox'], default='semantic',
                        help='The modality to visualize')
    parser.add_argument('--max_bbox', type=int, default=100,
                        help='The maximum number of bounding boxes to visualize')

    args = parser.parse_args()

    v = Kitti360Viewer3D(args.sequence)
    if args.mode == 'bbox':
        transformList = v.loadBoundingBoxes()

    if args.mode != 'bbox':
        transformList, bboxidList = v.loadBoundingBoxes()
        pclList = []

        pcdFileList = v.annotation3DPly.pcdFileList
        for idx, pcdFile in enumerate(pcdFileList):
            data = v.loadWindow(pcdFile, args.mode)  # data contains cat category
            if len(data) == 0:
                print('Warning: this point cloud doesnt contain cat category!')
                continue
            if idx == 0:
                instanceid = np.unique(data[:, 7] % 1000).astype(np.int64)
            else:
                last_instanceid = instanceid
                new_instanceid = np.unique(data[:, 7] % 1000).astype(np.int64)
                instanceid = [new_instanceid[i] for i in range(len(new_instanceid)) if
                              new_instanceid[i] not in last_instanceid]
            for iid in instanceid:
                mask = np.where(data[:, 7] % 1000 == iid)
                pcd_ori = np.column_stack((data[mask][:, :3], data[mask][:, 7] % 1000))
                pclList.append(pcd_ori)
        pcl_dict = {}
        for i, pcl in enumerate(pclList):
            pcl_dict['pointcloud' + str(i)] = [int(pcl[0, 3]), pcl[:, :3]]

        save_fold = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..', 'data_3d_car_pointcloud',
                                 'car')
        os.makedirs(save_fold, exist_ok=True)

        for dist_key, dist_item in pcl_dict.items():
            ins_id = dist_item[0]
            pcd_ori = dist_item[1]
            bboxid = bboxidList[0]
            while bboxid in bboxidList:
                if bboxid == ins_id:
                    tr_ind = bboxid - 1
                    bboxes_vet = np.array(v.bboxes[tr_ind].vertices)
                    sx = np.linalg.norm(bboxes_vet[0] - bboxes_vet[5])
                    sy = np.linalg.norm(bboxes_vet[0] - bboxes_vet[2])
                    sz = np.linalg.norm(bboxes_vet[0] - bboxes_vet[1])

                    R = transformList[tr_ind][:3, :3]
                    R = np.concatenate([R[:, 0] / sx, R[:, 1] / sy, R[:, 2] / sz]).reshape(3, 3).T
                    R = np.linalg.inv(R)
                    T = transformList[tr_ind][:3, 3]
                    pcd_can = np.matmul(R, pcd_ori.transpose()).transpose() - R @ T
                    r = Rot.from_euler('x', -90, degrees=True)
                    pcd_can = r.apply(pcd_can)
                    np.save(os.path.join(save_fold, str(ins_id) + '_canonical.npy'), pcd_can)
                bboxid = bboxid + 1

    else:
        if not len(v.bboxes):
            raise RuntimeError('No bounding boxes found! Please set KITTI360_DATASET in your environment path')

        # group the bboxes by windows
        windows_unique = np.unique(np.array(v.bboxes_window), axis=0)
        for window in windows_unique:
            bboxes = [v.bboxes[i] for i in range(len(v.bboxes)) if v.bboxes_window[i][0] == window[0]]
            print('Visualizing %06d_%06d with %d objects' % (window[0], window[1], len(bboxes)))
            if len(bboxes) > args.max_bbox:
                print('Randomly sample %d/%d bboxes for rendering efficiency' % (args.max_bbox, len(bboxes)))
                random_list = np.random.permutation(len(bboxes))[:args.max_bbox]
                bboxes = [bboxes[i] for i in random_list]
            open3d.visualization.draw_geometries(bboxes)

    exit()
