import os
import cv2
import tempfile
import shutil
import subprocess
import numpy as np
from tqdm import tqdm

from pose_pipeline import VideoInfo, PersonBbox, SMPLPerson


def video_overlay(
    video,
    output_name,
    callback,
    downsample=4,
    codec="MP4V",
    blur_faces=False,
    compress=True,
    bitrate="5M",
    max_frames=None,
):
    """Process a video and create overlay image

    Args:
        video (str): filename for source
        output_name (str): output filename
        callback (fn(im, idx) -> im): method to overlay frame
    """

    cap = cv2.VideoCapture(video)

    # get info
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fps = cap.get(cv2.CAP_PROP_FPS)

    # configure output
    output_size = (int(w / downsample), int(h / downsample))

    fourcc = cv2.VideoWriter_fourcc(*codec)
    out = cv2.VideoWriter(output_name, fourcc, fps, output_size)

    if blur_faces:
        blur = FaceBlur()

    if max_frames:
        total_frames = max_frames

    for idx in tqdm(range(total_frames)):

        ret, frame = cap.read()
        if not ret or frame is None:
            break

        # process image in RGB format
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        out_frame = callback(frame, idx)

        if blur_faces:
            out_frame = blur(out_frame)

        # move back to BGR format and write to movie
        out_frame = cv2.cvtColor(out_frame, cv2.COLOR_RGB2BGR)
        out_frame = cv2.resize(out_frame, output_size)
        out.write(out_frame)

    out.release()
    cap.release()

    if compress:
        fd, temp = tempfile.mkstemp(suffix=".mp4")
        subprocess.run(["ffmpeg", "-y", "-i", output_name, "-c:v", "libx264", "-b:v", bitrate, temp])
        os.close(fd)
        shutil.move(temp, output_name)


def draw_keypoints(image, keypoints, radius=10, threshold=0.2, color=(255, 255, 255), border_color=(0, 0, 0)):
    """Draw the keypoints on an image"""
    image = image.copy()
    keypoints = keypoints.copy()
    keypoints[..., 0] = np.clip(keypoints[..., 0], 0, image.shape[1])
    keypoints[..., 1] = np.clip(keypoints[..., 1], 0, image.shape[0])
    for i in range(keypoints.shape[0]):
        if keypoints[i, -1] > threshold:
            cv2.circle(image, (int(keypoints[i, 0]), int(keypoints[i, 1])), radius, border_color, -1)
            if radius > 2:
                cv2.circle(image, (int(keypoints[i, 0]), int(keypoints[i, 1])), radius - 2, color, -1)
    return image


def get_smpl_callback(key, poses, betas, cams):
    from pose_estimation.body_models.smpl import SMPL
    from pose_estimation.util.pyrender_renderer import PyrendererRenderer

    height, width = (VideoInfo & key).fetch1("height", "width")

    valid_idx = np.where((PersonBbox & key).fetch1("present"))[0]

    smpl = SMPL()
    renderer = PyrendererRenderer(smpl.get_faces(), img_size=(height, width))
    verts = smpl(poses, betas)[0].numpy()

    joints2d = (SMPLPerson & key).fetch1("joints2d")

    def overlay(frame, idx, renderer=renderer, verts=verts, cams=cams, joints2d=joints2d):

        smpl_idx = np.where(valid_idx == idx)[0]
        if len(smpl_idx) == 1:
            frame = renderer(verts[smpl_idx[0]], cams[smpl_idx[0]], frame)
            frame = draw_keypoints(frame, joints2d[smpl_idx[0]], radius=4)
        return frame

    return overlay
