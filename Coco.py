import json
import os
import random
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk

try:
    from pycocotools import mask as mask_utils
except ImportError:
    mask_utils = None

import colorsys

import sys


def random_color():
    return tuple(random.randint(200, 255) for _ in range(3))

def darker(color):
    """Return white or black based on background color brightness for better contrast."""
    r, g, b = [c / 255.0 for c in color]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    #h = (h + 0.5) % 1.0  # rotate hue for contrast
    l = min(0.7, max(0.3, 1 - l))  # ensure mid-range brightness
    s = min(1.0, s * 1.3)    # boost saturation
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return tuple(int(c * 255) for c in (r2, g2, b2))

class CocoPreviewer:
    """Loads COCO annotations and handles rendering masks, bboxes, and labels."""
    if hasattr(sys, '_MEIPASS'):
    # Running from the PyInstaller bundled executable
        base_path = sys._MEIPASS
    else:
        # Running from the script
        base_path = os.path.dirname(os.path.abspath(__file__))

    fonts_folder = os.path.join(base_path, "fonts")
    def __init__(self, coco_json_path, images_folder, image_index, image_index_scale):
        with open(coco_json_path, 'r', encoding="utf-8") as f:
            coco = json.load(f)
        self.images_folder = images_folder
        self.imgs = {img['id']: img for img in coco.get('images', [])}
        image_index.config(to=len(self.imgs))
        image_index_scale.config(to=len(self.imgs))
        self.anns = {}
        for ann in coco.get('annotations', []):
            self.anns.setdefault(ann['image_id'], []).append(ann)
        self.cats = {cat['id']: cat['name'] for cat in coco.get('categories', [])}
        self.colors = {ann['id']: random_color() for ann in coco.get('annotations', [])}
        self._cache = {}

    def _load(self, image_id):
        if image_id in self._cache:
            return self._cache[image_id].copy()
        info = self.imgs.get(image_id)
        if not info:
            raise KeyError(f"Image {image_id} not found")
        path = os.path.join(self.images_folder, info['file_name'])
        img = Image.open(path).convert('RGB')
        self._cache[image_id] = img
        return img.copy()

    def draw(self, image_id, mask_opacity=120, bbox_opacity=200, draw_bbox=True,
         bbox_width=2, mask_outline=2, draw_labels=True, label_size=20,
         max_size=250):
        """Return PIL image with annotations overlaid."""
        base = self._load(image_id).convert('RGBA')
        w, h = base.size
        scale = min(max_size / w, max_size / h, 1.0)
        new_size = int(w * scale), int(h * scale)
        base = base.resize(new_size, Image.Resampling.NEAREST)

        overlay = Image.new('RGBA', base.size)
        draw_ov = ImageDraw.Draw(overlay)
        positions = []
        # "Rumble Strike.otf"
        # "Hello Newyork.otf" 
        # "cheering section.otf"
        # "nightbird.otf"


        #
        font_path = os.path.join(self.fonts_folder, "nightbird.otf")
        font = ImageFont.truetype(font_path, label_size)
        box = []
        for ann in self.anns.get(image_id, []):
            # Handle pure bbox-only annotations
            bbox = ann.get('bbox')
            seg = ann.get('segmentation')
            bbox_coords = None
            color = self.colors.get(ann['id'], (255, 255, 255))
            name = self.cats.get(ann['category_id'], str(ann['category_id']))
            is_bbox = False
            # Handle bounding boxes if no segmentation
            if (not seg or seg == []) and bbox:
                # COCO bbox format: [x, y, width, height]
                x0, y0, bw, bh = bbox
                x1, y1 = x0 + bw, y0 + bh
                # scale coordinates
                coords = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
                rect_pts = [(coords[0], coords[1]), (coords[2], coords[3])]
                box.append((rect_pts, color))
                bbox_coords = coords
                is_bbox = True

            # Handle segmentation if available
            if isinstance(seg, list):
                xs, ys = [], []
                for polys in seg:
                    poly = [(polys[i] * scale, polys[i+1] * scale) for i in range(0, len(polys), 2)]
                    xs.extend(x for x, _ in poly)
                    ys.extend(y for _, y in poly)
                    draw_ov.polygon(poly, fill=color + (mask_opacity,), outline=color + (mask_opacity,))
                    if mask_outline:
                        draw_ov.line(poly + [poly[0]], fill=color + (255,), width=mask_outline)
                if xs and ys:
                    coords = (min(xs), min(ys), max(xs), max(ys))
                    rect_pts = [(coords[0], coords[1]), (coords[2], coords[3])]
                    box.append((rect_pts, color))
                    bbox_coords = coords

            # Handle RLE segmentation
            elif isinstance(seg, dict) and mask_utils:
                rle = seg
                if isinstance(rle.get('counts'), list):
                    h0, w0 = h / scale, w / scale
                    rle = mask_utils.frPyObjects(rle, int(h0), int(w0))
                m = mask_utils.decode(rle)
                mask_img = Image.fromarray((m * 255).astype('uint8')).resize(base.size, Image.NEAREST)
                overlay.paste(color + (mask_opacity,), mask=mask_img)
                bb = mask_img.getbbox()
                if bb:
                    coords = bb
                    rect_pts = [(coords[0], coords[1]), (coords[2], coords[3])]
                    box.append((rect_pts, color))
                    bbox_coords = coords

            # Collect label position (center of bbox)
            if draw_labels and not is_bbox and not draw_bbox and bbox_coords:
                # Get center of the bounding box for label
                x0, y0, x1, y1 = bbox_coords
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2  # center of the bbox
                positions.append(((cx, cy), name, color))
            elif draw_labels and bbox_coords:
                positions.append(((bbox_coords[0], bbox_coords[1]), name, color))

        combined = Image.alpha_composite(base, overlay)
        overlay = Image.new('RGBA', base.size)
        draw_ov = ImageDraw.Draw(overlay)

        if draw_bbox:
            for rect_pts, color in box:
                draw_ov.rectangle(rect_pts, outline=color + (bbox_opacity,), width=bbox_width)
        #combined = Image.alpha_composite(base, overlay)
        #draw_final = ImageDraw.Draw(combined, mode="RGBA")
        for (x, y), txt, col in positions:
            #overlay = Image.new('RGBA', base.size)
            #draw_ov = ImageDraw.Draw(overlay)
            txt = f"{txt}"
            text_bbox = draw_ov.textbbox((0, 0), txt, font=font)
            padding = label_size/4
            rect_coords = (
                x,
                y,
                x + text_bbox[2] - text_bbox[0] + padding * 2,
                y + text_bbox[3] - text_bbox[1] + padding * 2,
            )
            draw_ov.rectangle(rect_coords, fill=col + (bbox_opacity,))

        combined = Image.alpha_composite(combined, overlay)
        for (x, y), txt, col in positions:
            overlay = Image.new('RGBA', base.size)
            draw_ov = ImageDraw.Draw(overlay)
            txt = f"{txt}"
            text_bbox = draw_ov.textbbox((0, 0), txt, font=font)
            padding = label_size/4
            rect_coords = (
                x,
                y,
                x + text_bbox[2] - text_bbox[0] + padding * 2,
                y + text_bbox[3] - text_bbox[1] + padding * 2,
            )        
            draw_ov.text((x+padding, y+padding/4), txt, fill=darker(col), font=font)
            combined = Image.alpha_composite(combined, overlay)
        
        return combined


class PreviewGUI:
    """Tkinter GUI for live COCO annotation preview with prefs persistence."""

    PREFS_FILE = 'prefs.json'

    def __init__(self, root):
        self.root = root
        root.title('COCO Live Preview')
        root.resizable(False, False)
        self.preview = None
        self.lock = threading.Lock()
        self._vars()
        self._widgets()
        self._load_prefs()
        
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _vars(self):
        self.params = {
            'coco': tk.StringVar(), 'folder': tk.StringVar(), 'id': tk.IntVar(value=1),
            'mask_op': tk.IntVar(value=155), 'bbox_op': tk.IntVar(value=165),
            'bbox_w': tk.IntVar(value=4), 'mask_out': tk.IntVar(value=2),
            'draw_box': tk.BooleanVar(value=True), 'draw_lbl': tk.BooleanVar(value=True),
            'lbl_sz': tk.IntVar(value=14), 'max_sz': tk.IntVar(value=560)
        }
    
    def _widgets(self):
        frm = tk.Frame(self.root, padx=10, pady=10)
        frm.grid(row=0, column=0, sticky='nw', padx=20, pady=20)

        # COCO JSON and Images Dir Section
        settings_frame = tk.LabelFrame(frm, text="Source", padx=10, pady=10)
        settings_frame.grid(row=0, column=0, sticky='ew', pady=10)

        tk.Label(settings_frame, text='COCO JSON:', width=15).grid(row=0, column=0)
        tk.Entry(settings_frame, textvariable=self.params['coco']).grid(row=0, column=1, sticky="ew")
        tk.Button(settings_frame, text='Browse', command=lambda: self._browse('coco')).grid(row=0, column=2)

        tk.Label(settings_frame, text='Images Directory:', width=15).grid(row=1, column=0)
        tk.Entry(settings_frame, textvariable=self.params['folder']).grid(row=1, column=1, sticky="ew")
        tk.Button(settings_frame, text='Browse', command=lambda: self._browse('folder')).grid(row=1, column=2)

        settings_frame.columnconfigure(1, weight=1)

        # Image Settings Section
        image_frame = tk.Frame(frm)
        image_frame.grid(row=3, column=0, sticky="w", pady=10)

        small_frame = tk.LabelFrame(image_frame, text="Image ID", padx=10, pady=10)
        small_frame.grid(row=0, column=1, sticky='n', pady=10)

        self.image_index = tk.Spinbox(small_frame, from_=1, to=999999, width=5, textvariable=self.params['id'], command=self._update)
        self.image_index.grid(row=1, column=0)

        self.image_index_scale = tk.Scale(small_frame, from_=1, to=99999, orient='horizontal', variable=self.params["id"], command=lambda e: self._update())
        self.image_index_scale.grid(row=0, column=0, sticky='w')

        # Options Section: Checkboxes for Draw BBox and Draw Labels

        # Settings Section: Sliders
        sliders_frame = tk.LabelFrame(image_frame, text="Options", padx=10, pady=10)
        sliders_frame.grid(row=0, column=0, sticky='w', pady=10)

        opts = [('Draw BBox', 'draw_box'), ('Draw Labels', 'draw_lbl')]
        for a, (txt, key) in enumerate(opts):
            tk.Checkbutton(sliders_frame, text=txt, variable=self.params[key], command=self._update).grid(row=0, column=a, sticky='w')

        sliders = [
            ('Label Size', 'lbl_sz', 10, 100), ('BBox Width', 'bbox_w', 1, 10),
            ('BBox Opacity', 'bbox_op', 0, 255), ('Mask Opacity', 'mask_op', 0, 255),
            ('Mask Outline', 'mask_out', 0, 10), ('Max Size', 'max_sz', 250, 1000)
        ]
        for i, (txt, key, lo, hi) in enumerate(sliders):
            i += a
            tk.Label(sliders_frame, text=txt).grid(row=i, column=0, sticky='w')
            tk.Scale(sliders_frame, from_=lo, to=hi, orient='horizontal', variable=self.params[key], command=lambda e: self._update()).grid(row=i, column=1)

        # Canvas for Image Display
        ms = self.params['max_sz'].get()
        self.canvas = tk.Canvas(self.root, width=ms, height=ms, bg='#333')
        self.canvas.grid(row=0, column=1, rowspan=10, padx=10, pady=10)

        # Keyboard bindings for navigation
        self.root.bind('<KeyPress-Left>', lambda e: self._change_image(-1))
        self.root.bind('<KeyPress-Down>', lambda e: self._change_image(-1))
        self.root.bind('<KeyPress-Right>', lambda e: self._change_image(1))
        self.root.bind('<KeyPress-Up>', lambda e: self._change_image(1))
        self.root.bind('<Enter>', lambda e: self._update())

    def _browse(self, key):
        if key == 'coco':
            path = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        else:
            path = filedialog.askdirectory()
        if path:
            self.params[key].set(path)
            self._update()
   
    def _update(self):
        if not (self.params['coco'].get() and self.params['folder'].get()):
            return
        with self.lock:
            if not self.preview:
                try:
                    self.preview = CocoPreviewer(
                        self.params['coco'].get(), self.params['folder'].get(), self.image_index, self.image_index_scale)
                except Exception as e:
                    messagebox.showerror('Error', str(e))
                    return
            try:
                img = self.preview.draw(
                    self.params['id'].get(), self.params['mask_op'].get(),
                    self.params['bbox_op'].get(), self.params['draw_box'].get(),
                    self.params['bbox_w'].get(), self.params['mask_out'].get(),
                    self.params['draw_lbl'].get(), self.params['lbl_sz'].get(),
                    self.params['max_sz'].get()
                )
                self._show(img)
            except Exception as e:
                messagebox.showerror('Preview error', str(e))

    def _show(self, img):
        ms = self.params['max_sz'].get()
        self.canvas.config(width=ms, height=ms, highlightthickness=0)
        self.canvas.delete('all')
        self.photo = ImageTk.PhotoImage(img)
        w, h = img.size
        x = (ms - w) // 2
        y = (ms - h) // 2
        self.canvas.create_image(x, y, anchor='nw', image=self.photo)

    def _change_image(self, delta):
        current_id = self.params['id'].get()
        max_id = int(self.image_index['to'])
        if current_id + delta >= 1 and current_id + delta <= max_id:
            self.params['id'].set(current_id + delta)
            self._update()

    def _load_prefs(self):
        if os.path.exists(self.PREFS_FILE):
            try:
                with open(self.PREFS_FILE, encoding="utf-8") as f:
                    prefs = json.load(f)
                for k, var in self.params.items():
                    if k in prefs:
                        var.set(prefs[k])
                self._update()
            except Exception:
                pass

    def _save_prefs(self):
        prefs = {k: var.get() for k, var in self.params.items()}
        try:
            with open(self.PREFS_FILE, 'w', encoding="utf-8") as f:
                json.dump(prefs, f, indent=2)
        except Exception:
            pass

    def _on_close(self):
        self._save_prefs()
        self.root.destroy()


if __name__ == '__main__':
    " View COCO annotations in a tkinter GUI "
    root = tk.Tk()
    PreviewGUI(root)
    root.mainloop()
