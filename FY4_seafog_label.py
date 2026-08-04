# -*- coding: utf-8 -*-
"""
海雾标注工具 (风云4B HDF直读版 1x3界面)
功能：
1. 直接读取 FY-4B HDF原始数据 (2km & 4km分文件读取)，利用 satpy 动态生成夜间微物理 RGB。
2. 一行三列界面：左(原图+站点) | 中(交互操作区+超像素边界) | 右(二值掩膜)。
3. 根据风云文件名(14位UTC时间)自动匹配观测站CSV数据。
4. 界面自适应系统屏幕，支持自定义掩膜颜色。

依赖库：
pip install scikit-image pillow pandas opencv-python satpy pyresample shapely
"""

import os
import glob
import sys
import re
import json
import traceback
import warnings
import numpy as np
import pandas as pd
import cv2
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
from datetime import datetime, timedelta
import matplotlib.colors as mcolors

# 引入卫星数据处理库
try:
    from satpy import Scene
    from pyresample.geometry import AreaDefinition
except ImportError:
    print("错误：缺少 satpy 或 pyresample 库。")
    print("请使用 conda 安装: conda install -c conda-forge satpy pyresample")
    sys.exit(1)

# 引入 PIL 用于绘制中文
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    pass

# 引入超像素分割库
try:
    from skimage.segmentation import slic, find_boundaries
except ImportError:
    pass

warnings.filterwarnings('ignore')

# ================= 全局配置字典 (默认值) =================
CONFIG = {
    "INPUT_HDF_2KM_DIR": r"H:\2021_2km",
    "INPUT_HDF_4KM_DIR": r"H:\2021_4km",
    "MERGED_DATA_ROOT": r"G:\remote_fog\SP_analysis\combine_new",
    "FINAL_MASK_DIR": r"F:\fy\mask",
    "VISUAL_OUTPUT_DIR": r"F:\fy\vis",
    "OVERLAY_COLOR_HEX": "#FF0000"  # 默认掩膜颜色(红色)
}

CONFIG_FILE = "fy4b_path_config.json"

# 固定参数 (基于风云数据的修改)
VISUALIZATION_EXTENT = [119.0, 128.0, 27.0, 36.0]  # [lon_min, lon_max, lat_min, lat_max]
GRID_RES_DEG = 0.02
TIME_WINDOW_HOURS = 1.0
SLIC_N_SEGMENTS = 1000
SLIC_COMPACTNESS = 20.0
SLIC_SIGMA = 1.0
INTERACTIVE_MASK_ALPHA = 0.3

# UI自适应参数
MAX_UI_WIDTH = 1450
MAX_UI_HEIGHT_IMG = 650
STATUS_BAR_HEIGHT = 180


# ================= GUI 配置窗口类 =================

class PathConfigDialog:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("风云4B 海雾标注工具 - 环境配置")
        self.root.geometry("700x500")
        self.root.resizable(False, False)
        self.cancelled = True

        self.load_config()

        tk.Label(self.root, text="请确认风云4B数据路径与参数配置", font=("微软雅黑", 14, "bold")).pack(pady=15)
        self.frame = tk.Frame(self.root)
        self.frame.pack(padx=20, pady=5, fill="x")

        self.entries = {}
        self.create_row("2KM HDF 数据目录:", "INPUT_HDF_2KM_DIR")
        self.create_row("4KM HDF 数据目录:", "INPUT_HDF_4KM_DIR")
        self.create_row("观测数据(CSV)目录:", "MERGED_DATA_ROOT")
        self.create_row("掩膜输出目录(单通道):", "FINAL_MASK_DIR")
        self.create_row("1x3效果图输出目录:", "VISUAL_OUTPUT_DIR")

        self.create_color_row("自定义掩膜颜色:", "OVERLAY_COLOR_HEX")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=30)

        tk.Button(btn_frame, text="开始处理", bg="#4CAF50", fg="white", font=("微软雅黑", 12),
                  width=15, command=self.on_start).pack(side="left", padx=20)
        tk.Button(btn_frame, text="退出", bg="#f44336", fg="white", font=("微软雅黑", 12),
                  width=10, command=self.on_cancel).pack(side="left", padx=20)

        tk.Label(self.root, text="提示: 工具将分别读取两目录数据合并生成RGB标注。", fg="gray").pack(side="bottom",
                                                                                                   pady=10)

    def create_row(self, label_text, key):
        row = tk.Frame(self.frame)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label_text, width=20, anchor="e").pack(side="left")
        entry = tk.Entry(row)
        entry.insert(0, CONFIG[key])
        entry.pack(side="left", fill="x", expand=True, padx=5)
        self.entries[key] = entry
        tk.Button(row, text="浏览...", command=lambda k=key: self.browse_dir(k)).pack(side="left")

    def create_color_row(self, label_text, key):
        row = tk.Frame(self.frame)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label_text, width=20, anchor="e").pack(side="left")
        self.color_btn = tk.Button(row, text="", width=10, bg=CONFIG[key], command=lambda: self.choose_color(key))
        self.color_btn.pack(side="left", padx=5)

    def choose_color(self, key):
        color_code = colorchooser.askcolor(title="选择掩膜颜色", initialcolor=CONFIG[key])[1]
        if color_code:
            CONFIG[key] = color_code
            self.color_btn.config(bg=color_code)

    def browse_dir(self, key):
        path = filedialog.askdirectory(initialdir=self.entries[key].get(), title=f"选择 {key}")
        if path:
            self.entries[key].delete(0, tk.END)
            self.entries[key].insert(0, path)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    CONFIG.update(json.load(f))
            except:
                pass

    def save_config(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, indent=4, ensure_ascii=False)
        except:
            pass

    def on_start(self):
        for key, entry in self.entries.items():
            val = entry.get().strip()
            if not val:
                messagebox.showwarning("警告", f"{key} 不能为空！")
                return
            CONFIG[key] = val
        self.save_config()
        self.cancelled = False
        self.root.destroy()

    def on_cancel(self):
        self.cancelled = True
        self.root.destroy()

    def show(self):
        self.root.mainloop()
        return not self.cancelled


# ================= 辅助函数 =================

def hex_to_bgr(hex_str):
    hex_str = hex_str.lstrip('#')
    r, g, b = tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def cv2_img_add_text(img, text, left, top, text_color=(255, 255, 255), text_size=20):
    if isinstance(img, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    font_paths = [
        "simhei.ttf", "msyh.ttc", "simsun.ttc",
        "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"
    ]
    font = None
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, text_size)
            break
        except:
            continue
    if font is None: font = ImageFont.load_default()
    draw.text((left, top), text, fill=text_color, font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def extract_time_from_fy4b_filename(filepath):
    """
    从风云4B文件名解析时间。
    风云数据文件名通常自带 14位 UTC时间，例如 20240315000000
    无需再减去8小时。
    """
    basename = os.path.basename(filepath)
    match = re.search(r'(\d{14})', basename)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    raise ValueError(f"无法从风云文件名解析14位时间: {basename}")


def get_visibility_color(val, cmap, norm):
    rgba = cmap(norm(val))
    return (int(rgba[2] * 255), int(rgba[1] * 255), int(rgba[0] * 255))


def get_visibility_cmap():
    levels = [0, 1.0, 2.0, 5.0, 10.0, 50.0]
    colors = ['#FF0000', '#FF4500', '#FFFF00', '#7FFF00', '#0000FF']
    cmap = mcolors.ListedColormap(colors)
    norm = mcolors.BoundaryNorm(levels, cmap.N)
    return cmap, norm, levels, colors


def get_obs_data(sat_time_utc, extent):
    year_str = str(sat_time_utc.year)
    date_str = sat_time_utc.strftime("%Y%m%d")
    csv_path = os.path.join(CONFIG["MERGED_DATA_ROOT"], year_str, f"MD_ICOADS_{date_str}.csv")
    if not os.path.exists(csv_path): return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        time_diff = (df['Timestamp'] - sat_time_utc).abs()
        mask_time = time_diff <= timedelta(hours=TIME_WINDOW_HOURS)
        mask_geo = (df['Lon'] >= extent[0]) & (df['Lon'] <= extent[1]) & (df['Lat'] >= extent[2]) & (
                df['Lat'] <= extent[3])
        obs_df = df[mask_time & mask_geo].copy()
        obs_df.dropna(subset=['Visibility_km'], inplace=True)
        return obs_df
    except:
        return pd.DataFrame()


def draw_legend(img, start_x, start_y):
    cmap, norm, levels, _ = get_visibility_cmap()
    TITLE_SIZE, ITEM_SIZE, BOX_W, BOX_H = 16, 14, 30, 16

    img = cv2_img_add_text(img, "能见度色标(km):", start_x, start_y, (220, 220, 220), TITLE_SIZE)
    curr_x = start_x + 130
    curr_y = start_y + 2

    for i in range(len(levels) - 1):
        mid_val = (levels[i] + levels[i + 1]) / 2.0
        color = get_visibility_color(mid_val, cmap, norm)
        cv2.rectangle(img, (curr_x, curr_y), (curr_x + BOX_W, curr_y + BOX_H), color, -1)
        img = cv2_img_add_text(img, str(int(levels[i])), curr_x, curr_y + BOX_H + 4, (200, 200, 200), ITEM_SIZE)
        curr_x += BOX_W

    img = cv2_img_add_text(img, f">{int(levels[-2])}", curr_x - 10, curr_y + BOX_H + 4, (200, 200, 200), ITEM_SIZE)

    shape_y = start_y + 55
    img = cv2_img_add_text(img, "数据点形状:", start_x, shape_y - 10, (220, 220, 220), TITLE_SIZE)

    shape_x = start_x + 130
    cv2.circle(img, (shape_x + 12, shape_y), 12, (255, 255, 255), -1)
    cv2.circle(img, (shape_x + 12, shape_y), 9, (0, 0, 0), -1)
    img = cv2_img_add_text(img, "站点", shape_x + 32, shape_y - 10, (200, 200, 200), ITEM_SIZE + 2)

    shape_x += 100
    cv2.drawMarker(img, (shape_x + 12, shape_y), (255, 255, 255), cv2.MARKER_STAR, 24, 2)
    img = cv2_img_add_text(img, "船舶", shape_x + 32, shape_y - 10, (200, 200, 200), ITEM_SIZE + 2)

    return img


# ================= 风云数据解析模块 =================

def normalize_channel(data, min_val, max_val):
    data = np.asanyarray(data)
    return np.clip((data - min_val) / (max_val - min_val), 0, 1)


def create_target_area(extent, grid_res_deg):
    lon_min, lon_max, lat_min, lat_max = extent
    proj_id = 'east_asia_fog_research'
    proj_dict = {'proj': 'longlat', 'ellps': 'WGS84'}
    width = int((lon_max - lon_min) / grid_res_deg)
    height = int((lat_max - lat_min) / grid_res_deg)
    area_def = AreaDefinition(proj_id, 'Area for FY4B Fog', 'longlat', proj_dict,
                              width, height, [lon_min, lat_min, lon_max, lat_max])
    return area_def


def generate_fy4b_bgr(file_2km, file_4km, extent):
    """
    读取风云4B数据，返回用于OpenCV处理的 BGR numpy uint8 数组
    """
    print(f"  -> 正在利用 satpy 加载与重采样 HDF 数据，这可能需要几秒钟...")
    scn = Scene(filenames=[file_2km, file_4km], reader='agri_fy4b_l1')
    scn.load(['C07', 'C13', 'C14'])

    target_area = create_target_area(extent, grid_res_deg=GRID_RES_DEG)
    local_scn = scn.resample(target_area)

    bt3_75_c = local_scn['C07'].values - 273.15
    bt10_8_c = local_scn['C13'].values - 273.15
    bt12_0_c = local_scn['C14'].values - 273.15

    # 3.75通道中值滤波去噪
    nan_mask = np.isnan(bt3_75_c)
    bt3_75_filled = np.nan_to_num(bt3_75_c)
    denoised_bt3_75 = cv2.medianBlur(bt3_75_filled.astype(np.float32), 3)
    denoised_bt3_75[nan_mask] = np.nan

    # 计算夜间微物理 RGB
    R = bt12_0_c - bt10_8_c
    G = bt10_8_c - denoised_bt3_75
    B = bt10_8_c

    R_norm = normalize_channel(R, -4, 2)
    G_norm = normalize_channel(G, 0, 10)
    B_norm = normalize_channel(B, -29, 19)

    rgb_image_float = np.dstack((R_norm, G_norm, B_norm))

    # 转换为 OpenCV 标准 BGR uint8 (处理 NaN 设为黑色)
    rgb_image_uint8 = np.nan_to_num(rgb_image_float * 255).astype(np.uint8)
    bgr_image = cv2.cvtColor(rgb_image_uint8, cv2.COLOR_RGB2BGR)

    return bgr_image


# ================= 核心业务交互流 =================

current_segments, current_selected_ids = None, set()


def mouse_callback(event, x, y, flags, param):
    global current_selected_ids
    scale = param['scale']
    W_scaled, H_scaled = param['W_scaled'], param['H_scaled']
    target_id = -1

    if y < H_scaled and W_scaled <= x < 2 * W_scaled:
        orig_x = int((x - W_scaled) / scale)
        orig_y = int(y / scale)
        if orig_y < current_segments.shape[0] and orig_x < current_segments.shape[1]:
            target_id = current_segments[orig_y, orig_x]

    if target_id != -1:
        if (event == cv2.EVENT_MOUSEMOVE and (flags & cv2.EVENT_FLAG_CTRLKEY)) or event == cv2.EVENT_LBUTTONDOWN:
            current_selected_ids.add(target_id)
        elif event == cv2.EVENT_RBUTTONDOWN and target_id in current_selected_ids:
            current_selected_ids.remove(target_id)


def process_images():
    global current_segments, current_selected_ids
    print("\n=== 开始交互式标注流程 ===")
    os.makedirs(CONFIG["FINAL_MASK_DIR"], exist_ok=True)
    os.makedirs(CONFIG["VISUAL_OUTPUT_DIR"], exist_ok=True)

    # 在2km特定目录搜寻 2km 文件
    hdf_2km_files = sorted(glob.glob(os.path.join(CONFIG["INPUT_HDF_2KM_DIR"], "*_2000M_*.HDF")))
    if not hdf_2km_files:
        print(f"错误: 在 {CONFIG['INPUT_HDF_2KM_DIR']} 未找到 *_2000M_*.HDF 文件")
        return False

    window_name = "FY-4B Fog Labeling Tool"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    cmap, norm, _, _ = get_visibility_cmap()
    custom_overlay_bgr = hex_to_bgr(CONFIG.get("OVERLAY_COLOR_HEX", "#FF0000"))

    for file_2km in hdf_2km_files:
        base_name_2km = os.path.basename(file_2km)

        # --- 智能匹配 4KM 文件 ---
        # 策略1：直接根据文件名替换寻找
        base_name_4km = base_name_2km.replace('2000M', '4000M')
        file_4km = os.path.join(CONFIG["INPUT_HDF_4KM_DIR"], base_name_4km)

        # 策略2：如果策略1失败，提取时间戳进行模糊匹配
        if not os.path.exists(file_4km):
            try:
                timestamp = extract_time_from_fy4b_filename(file_2km).strftime("%Y%m%d%H%M%S")
                search_pattern = os.path.join(CONFIG["INPUT_HDF_4KM_DIR"], f"*{timestamp}*4000M*.HDF")
                fallback_files = glob.glob(search_pattern)
                if fallback_files:
                    file_4km = fallback_files[0]
                else:
                    print(f"跳过: 在4km文件夹中找不到匹配的时间戳文件 (尝试匹配 {timestamp})")
                    continue
            except Exception as e:
                print(f"跳过: 找不到对应的 4000M 文件且时间戳提取失败 ({base_name_2km})")
                continue

        # 提取时间作为标识
        base_name = base_name_2km.replace(".HDF", "")
        mask_save_path = os.path.join(CONFIG["FINAL_MASK_DIR"], base_name + "_mask.png")
        visual_save_path = os.path.join(CONFIG["VISUAL_OUTPUT_DIR"], base_name + "_1x3.png")

        if os.path.exists(mask_save_path):
            print(f"跳过已处理文件: {base_name}")
            continue

        print(f"\n正在处理: {base_name}")

        # 调用 satpy 模块动态生成纯正无地图边框的底层卫星图
        try:
            img_origin = generate_fy4b_bgr(file_2km, file_4km, VISUALIZATION_EXTENT)
        except Exception as e:
            print(f"解析风云数据失败: {e}")
            continue

        H, W = img_origin.shape[:2]
        scale_w = MAX_UI_WIDTH / (3 * W)
        scale_h = MAX_UI_HEIGHT_IMG / H
        scale = min(1.0, scale_w, scale_h)
        target_W = int(W * scale)
        target_H = int(H * scale)

        # --- 图A: 左图(原图叠加站点) ---
        img_A = img_origin.copy()
        try:
            sat_time_utc = extract_time_from_fy4b_filename(file_2km)
            obs_df = get_obs_data(sat_time_utc, VISUALIZATION_EXTENT)
            if not obs_df.empty:
                min_lon, max_lon = VISUALIZATION_EXTENT[0], VISUALIZATION_EXTENT[1]
                min_lat, max_lat = VISUALIZATION_EXTENT[2], VISUALIZATION_EXTENT[3]
                for _, row in obs_df.iterrows():
                    lon, lat = row['Lon'], row['Lat']
                    vis, stype = row['Visibility_km'], row['Source_Type']
                    px = int(float(lon - min_lon) / (max_lon - min_lon) * W)
                    py = int(float(max_lat - lat) / (max_lat - min_lat) * H)
                    if 0 <= px < W and 0 <= py < H:
                        color = get_visibility_color(vis, cmap, norm)
                        if stype == 'Station':
                            cv2.circle(img_A, (px, py), 12, (255, 255, 255), -1)
                            cv2.circle(img_A, (px, py), 9, color, -1)
                        elif stype == 'ICOADS':
                            cv2.drawMarker(img_A, (px, py), color, cv2.MARKER_STAR, 24, 2)
        except Exception as e:
            print(f"  [信息] 站点映射未完成或无数据: {e}")

        # --- 准备工作: 超像素分割并获取细黑轮廓线 ---
        print(f"  -> 正在进行超像素分割计算...")
        img_rgb = cv2.cvtColor(img_origin, cv2.COLOR_BGR2RGB)
        current_segments = slic(img_rgb, n_segments=SLIC_N_SEGMENTS, compactness=SLIC_COMPACTNESS, sigma=SLIC_SIGMA,
                                start_label=1)

        boundaries = find_boundaries(current_segments, mode='inner')
        img_with_bound_bgr = img_origin.copy()
        img_with_bound_bgr[boundaries] = [0, 0, 0]

        current_selected_ids = set()
        cv2.setMouseCallback(window_name, mouse_callback,
                             param={'W_scaled': target_W, 'H_scaled': target_H, 'scale': scale})

        col1_x, col2_x, col3_x = 20, target_W + 20, 2 * target_W + 20

        while True:
            display_buffer = np.zeros((target_H + STATUS_BAR_HEIGHT, 3 * target_W, 3), dtype=np.uint8)
            display_buffer[target_H:, :] = (40, 40, 40)

            display_buffer[:target_H, 0:target_W] = cv2.resize(img_A, (target_W, target_H))

            overlay_B = img_with_bound_bgr.copy()
            final_mask = np.zeros((H, W), dtype=np.uint8)
            if current_selected_ids:
                for seg_id in current_selected_ids:
                    final_mask[current_segments == seg_id] = 255
                color_layer = np.zeros_like(img_origin)
                color_layer[:] = custom_overlay_bgr
                locs = final_mask == 255
                overlay_B[locs] = cv2.addWeighted(overlay_B[locs], 1.0 - INTERACTIVE_MASK_ALPHA, color_layer[locs],
                                                  INTERACTIVE_MASK_ALPHA, 0)

            display_buffer[:target_H, target_W:2 * target_W] = cv2.resize(overlay_B, (target_W, target_H))
            mask_rgb = cv2.cvtColor(final_mask, cv2.COLOR_GRAY2BGR)
            display_buffer[:target_H, 2 * target_W:3 * target_W] = cv2.resize(mask_rgb, (target_W, target_H))

            cv2.line(display_buffer, (target_W, 0), (target_W, target_H + STATUS_BAR_HEIGHT), (255, 255, 255), 2)
            cv2.line(display_buffer, (2 * target_W, 0), (2 * target_W, target_H + STATUS_BAR_HEIGHT), (255, 255, 255),
                     2)

            display_buffer = cv2_img_add_text(display_buffer, f"当前文件: {base_name[:30]}...", col1_x, target_H + 15,
                                              (255, 255, 0), 20)
            display_buffer = cv2_img_add_text(display_buffer, f"选中区块数: {len(current_selected_ids)}", col1_x,
                                              target_H + 45, (0, 255, 255), 18)
            display_buffer = draw_legend(display_buffer, col1_x, target_H + 80)

            display_buffer = cv2_img_add_text(display_buffer, "[左图] 原图+站点 | [中图] 交互 | [右图] 掩膜",
                                              col2_x, target_H + 15, (200, 255, 200), 20)
            display_buffer = cv2_img_add_text(display_buffer, "交互操作说明:", col2_x, target_H + 50, (220, 220, 220),
                                              18)
            display_buffer = cv2_img_add_text(display_buffer, "• [左键/Ctrl+滑动]: 选中", col2_x + 15, target_H + 85,
                                              (220, 220, 220), 16)
            display_buffer = cv2_img_add_text(display_buffer, "• [右键]: 取消选中", col2_x + 15, target_H + 115,
                                              (220, 220, 220), 16)

            display_buffer = cv2_img_add_text(display_buffer, "键盘快捷指令:", col3_x, target_H + 15, (100, 255, 100),
                                              20)
            display_buffer = cv2_img_add_text(display_buffer, "[S] : 保存并继续", col3_x + 15, target_H + 45,
                                              (100, 255, 100), 16)
            display_buffer = cv2_img_add_text(display_buffer, "[C] : 清空当前选择", col3_x + 15, target_H + 75,
                                              (100, 255, 100), 16)
            display_buffer = cv2_img_add_text(display_buffer, "[Q] : 跳过当前图片", col3_x + 15, target_H + 105,
                                              (100, 255, 100), 16)
            display_buffer = cv2_img_add_text(display_buffer, "[Esc]: 退出系统", col3_x + 15, target_H + 135,
                                              (255, 100, 100), 16)

            cv2.imshow(window_name, display_buffer)
            key = cv2.waitKey(20) & 0xFF

            if key == ord('s'):
                full_1x3_origin = np.hstack((img_A, overlay_B, mask_rgb))
                cv2.imwrite(mask_save_path, final_mask)
                cv2.imwrite(visual_save_path, full_1x3_origin)
                print(f"  -> 已保存掩膜及原始全景图: {base_name}")
                break
            elif key == ord('c'):
                current_selected_ids.clear()
            elif key == ord('q'):
                cv2.imwrite(mask_save_path, np.zeros((H, W), dtype=np.uint8))
                print(f"  -> 跳过当前图片: {base_name}")
                break
            elif key == 27:
                cv2.destroyAllWindows()
                return False

    cv2.destroyAllWindows()
    return True


def run_application():
    app = PathConfigDialog()
    if not app.show():
        print("用户取消操作，程序退出。")
        return

    print("=== 开始运行风云4B海雾标注工具 ===")
    print(f"读取2km路径: {CONFIG['INPUT_HDF_2KM_DIR']}")
    print(f"匹配4km路径: {CONFIG['INPUT_HDF_4KM_DIR']}")
    process_images()
    print("\n全部处理完毕。")


def main():
    try:
        run_application()
    except Exception as e:
        print("\n" + "!" * 50)
        print("程序发生严重错误 (Fatal Error):")
        print(traceback.format_exc())
        print("!" * 50 + "\n")
    finally:
        print("\n程序运行结束。请按回车键退出...")
        input()


if __name__ == "__main__":
    main()