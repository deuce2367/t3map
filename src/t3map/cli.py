#!/usr/bin/env python3
import json
import argparse
import csv
import matplotlib.cm as cm
import matplotlib.lines as mlines
import random
import glob
import sys
import math
import io
from PIL import Image
import matplotlib
# Use Agg backend for headless environments
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patheffects as PathEffects
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.transforms import Bbox
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import textwrap
import textwrap

def generate_points(n, lat_min, lat_max, lon_min, lon_max):
    points = []
    prefixes = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Gamma", "Nexus", "Omega"]
    for i in range(n):
        lat = random.uniform(lat_min, lat_max)
        lon = random.uniform(lon_min, lon_max)
        name = f"Site {random.choice(prefixes)}-{random.randint(10,99)}"
        value = random.randint(100, 1000)
        points.append({"lon": lon, "lat": lat, "name": name, "value": value})
    return points

MERCATOR_MAX = 20037508.34

def lonlat_to_merc(lon, lat):
    x = lon * MERCATOR_MAX / 180.0
    lat = max(-89.9, min(89.9, lat))
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * MERCATOR_MAX / 180.0
    return x, y

def merc_to_lonlat(x, y):
    lon = x * 180.0 / MERCATOR_MAX
    lat = math.atan(math.exp(y * math.pi / MERCATOR_MAX)) * 360.0 / math.pi - 90.0
    return lon, lat

def bbox_intersects(b1, b2):
    # b = (min_lon, min_lat, max_lon, max_lat)
    return not (b1[2] < b2[0] or b1[0] > b2[2] or b1[3] < b2[1] or b1[1] > b2[3])

def get_feature_bbox(feature):
    geom = feature.get("geometry")
    if not geom:
        return None
    
    coords = geom.get("coordinates", [])
    if not coords:
        return None
        
    def extract_coords(c):
        if not c:
            return []
        if isinstance(c[0], (int, float)):
            return [c]
        flat = []
        for sub in c:
            flat.extend(extract_coords(sub))
        return flat

    flat_coords = extract_coords(coords)
    if not flat_coords:
        return None
    
    lons = [c[0] for c in flat_coords]
    lats = [c[1] for c in flat_coords]
    return (min(lons), min(lats), max(lons), max(lats))

def create_polygon_patch(coords, facecolor, edgecolor, linewidth, alpha, zorder=1):
    vertices = []
    codes = []
    for ring in coords:
        if not ring:
            continue
        proj_ring = [lonlat_to_merc(pt[0], pt[1]) for pt in ring]
        vertices.extend(proj_ring)
        ring_codes = [Path.LINETO] * len(proj_ring)
        ring_codes[0] = Path.MOVETO
        ring_codes[-1] = Path.CLOSEPOLY
        codes.extend(ring_codes)
    if not vertices:
        return None
    path = Path(vertices, codes)
    patch = PathPatch(path, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth, alpha=alpha, zorder=zorder)
    return patch, path



def plot_geojson_layer(geojson_path, view_bbox, ax, args, merc_bounds, layer_type="land"):
    merc_min_x, merc_min_y, merc_max_x, merc_max_y = merc_bounds
    is_water = layer_type == "water"
    is_river = layer_type == "river"
    try:
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        features = data.get("features", [])
        print(f"Total features in {'water' if is_water else 'map'} geojson: {len(features)}")
        
        plotted_features = 0
        for feat in features:
            f_bbox = feat.get("bbox")
            if not f_bbox:
                f_bbox = get_feature_bbox(feat)
                
            if f_bbox and not bbox_intersects(f_bbox, view_bbox):
                continue
                
            geom = feat.get("geometry")
            if not geom:
                continue
                
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            props = feat.get("properties", {})
            name = props.get("name", "")
            if not name:
                name = props.get("name_en", "") # fallback
            if not name:
                name = props.get("NAME", "") # fallback for rivers
                
            if name:
                name = textwrap.fill(name, width=12)
            
            paths = []
            if gtype in ("Polygon", "MultiPolygon"):
                coords_list = [coords] if gtype == "Polygon" else coords
                for poly_coords in coords_list:
                    if layer_type == "land":
                        # Add filled polygon with facecolor AND edgecolor same
                        fill_res = create_polygon_patch(poly_coords, args.map_fill, args.map_fill, 0.1, 0.8, zorder=1)
                        if fill_res:
                            ax.add_patch(fill_res[0])
                            paths.append(fill_res[1])
                            
                        # Add independent borders using ax.plot for 100% reliability
                        for ring in poly_coords:
                            if not ring: continue
                            proj_ring = [lonlat_to_merc(pt[0], pt[1]) for pt in ring]
                            x = [pt[0] for pt in proj_ring]
                            y = [pt[1] for pt in proj_ring]
                            ax.plot(x, y, color=args.map_border, linewidth=args.border_width, alpha=0.8, zorder=3)
                    elif layer_type == "water":
                        fill_res = create_polygon_patch(poly_coords, 'none', 'none', 0, 0.0, zorder=0)
                        if fill_res:
                            paths.append(fill_res[1])
            elif gtype == "LineString" and is_river:
                merc_coords = [lonlat_to_merc(c[0], c[1]) for c in coords]
                is_vis = any(merc_min_x <= c[0] <= merc_max_x and merc_min_y <= c[1] <= merc_max_y for c in merc_coords)
                if is_vis:
                    x = [c[0] for c in merc_coords]
                    y = [c[1] for c in merc_coords]
                    ax.plot(x, y, color=args.bg_color, linewidth=1.5, zorder=2)
                    paths.append(Path(merc_coords))
            elif gtype == "MultiLineString" and is_river:
                for line_coords in coords:
                    merc_coords = [lonlat_to_merc(c[0], c[1]) for c in line_coords]
                    is_vis = any(merc_min_x <= c[0] <= merc_max_x and merc_min_y <= c[1] <= merc_max_y for c in merc_coords)
                    if is_vis:
                        x = [c[0] for c in merc_coords]
                        y = [c[1] for c in merc_coords]
                        ax.plot(x, y, color=args.bg_color, linewidth=1.5, zorder=2)
                        paths.append(Path(merc_coords))
                        
            # Check actual visibility
            view_bbox_merc = Bbox.from_extents(merc_min_x, merc_min_y, merc_max_x, merc_max_y)
            is_visible = any(p.intersects_bbox(view_bbox_merc) for p in paths)
            
            if not is_visible and layer_type != "feature":
                continue
            
            # Plot Polygon labels
            if is_river and name and args.show_map_labels:
                best_len = 0
                best_seg = None
                for p in paths:
                    verts = p.vertices
                    for i in range(len(verts)-1):
                        p1, p2 = verts[i], verts[i+1]
                        if (merc_min_x <= p1[0] <= merc_max_x and merc_min_y <= p1[1] <= merc_max_y) or \
                           (merc_min_x <= p2[0] <= merc_max_x and merc_min_y <= p2[1] <= merc_max_y):
                            seg_len = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
                            if seg_len > best_len:
                                best_len = seg_len
                                best_seg = (p1, p2)
                
                if best_seg and best_len > (merc_max_x - merc_min_x) * 0.02:
                    p1, p2 = best_seg
                    mid_x = (p1[0] + p2[0]) / 2.0
                    mid_y = (p1[1] + p2[1]) / 2.0
                    angle = math.degrees(math.atan2(p2[1]-p1[1], p2[0]-p1[0]))
                    if angle > 90: angle -= 180
                    elif angle < -90: angle += 180
                    
                    label_color = args.water_label_color
                    txt = ax.text(mid_x, mid_y, name, fontsize=6.5, fontweight='bold', fontstyle='italic',
                                  color=label_color, ha='center', va='center', rotation=angle, 
                                  zorder=2, clip_on=True, alpha=0.85)

            elif gtype in ("Polygon", "MultiPolygon") and name and args.show_map_labels:
                best_path = None
                max_vis_diag = 0
                best_min_vx = best_max_vx = best_min_vy = best_max_vy = 0
                
                for p in paths:
                    vx = [v[0] for v in p.vertices]
                    vy = [v[1] for v in p.vertices]
                    if not vx or not vy: continue
                    
                    p_min_x, p_max_x = min(vx), max(vx)
                    p_min_y, p_max_y = min(vy), max(vy)
                    
                    p_min_vx = max(merc_min_x, p_min_x)
                    p_max_vx = min(merc_max_x, p_max_x)
                    p_min_vy = max(merc_min_y, p_min_y)
                    p_max_vy = min(merc_max_y, p_max_y)
                    
                    if p_max_vx <= p_min_vx or p_max_vy <= p_min_vy:
                        continue
                        
                    vis_diag = math.hypot(p_max_vx - p_min_vx, p_max_vy - p_min_vy)
                    if vis_diag > max_vis_diag:
                        max_vis_diag = vis_diag
                        best_path = p
                        best_min_vx, best_max_vx, best_min_vy, best_max_vy = p_min_vx, p_max_vx, p_min_vy, p_max_vy

                if not best_path:
                    continue
                    
                min_vx, max_vx, min_vy, max_vy = best_min_vx, best_max_vx, best_min_vy, best_max_vy
                
                pref_x = props.get("label_x")
                pref_y = props.get("label_y")
                use_pref = pref_x is not None and pref_y is not None and \
                           view_bbox[0] <= pref_x <= view_bbox[2] and view_bbox[1] <= pref_y <= view_bbox[3]
                           
                if not use_pref:
                    if (max_vx - min_vx) < (merc_max_x - merc_min_x) * 0.05 and \
                       (max_vy - min_vy) < (merc_max_y - merc_min_y) * 0.05:
                        continue
                
                target_mx = (min_vx + max_vx) / 2.0
                target_my = (min_vy + max_vy) / 2.0
                
                valid_pts = []
                invalid_pts = []
                for ix in range(20):
                    for iy in range(20):
                        px = min_vx + (max_vx - min_vx) * (ix / 19.0)
                        py = min_vy + (max_vy - min_vy) * (iy / 19.0)
                        if best_path.contains_point((px, py)):
                            valid_pts.append((px, py))
                        else:
                            invalid_pts.append((px, py))
                            
                best_pt = None
                if valid_pts:
                    max_score = -float('inf')
                    for vx, vy in valid_pts:
                        if invalid_pts:
                            dist_to_inv = min((vx - ix)**2 + (vy - iy)**2 for ix, iy in invalid_pts)
                        else:
                            dist_to_inv = float('inf')
                            
                        dist_to_edge = min((vx - min_vx)**2, (vx - max_vx)**2, (vy - min_vy)**2, (vy - max_vy)**2)
                        min_safe_dist = min(dist_to_inv, dist_to_edge)
                        
                        # Maximize safety distance, gently penalize being far from bounding box center
                        center_dist = (vx - target_mx)**2 + (vy - target_my)**2
                        score = min_safe_dist - center_dist * 0.05
                        
                        if score > max_score:
                            max_score = score
                            best_pt = (vx, vy)
                
                anchor_mx, anchor_my = target_mx, target_my
                if best_pt:
                    anchor_mx, anchor_my = best_pt
                    
                if use_pref:
                    text_mx, text_my = lonlat_to_merc(pref_x, pref_y)
                else:
                    text_mx = anchor_mx
                    text_my = anchor_my

                label_color = args.water_label_color if is_water else args.map_label_color
                label_size = args.water_label_size if is_water else args.map_label_size
                
                poly_width = max_vx - min_vx
                poly_height = max_vy - min_vy
                view_width = merc_max_x - merc_min_x
                view_height = merc_max_y - merc_min_y
                
                if view_width > 0 and view_height > 0:
                    poly_diag = math.hypot(poly_width, poly_height)
                    view_diag = math.hypot(view_width, view_height)
                    ratio = poly_diag / view_diag
                    
                    if is_water:
                        if ratio < 0.25:
                            label_size = max(6.0, label_size * (ratio / 0.25))
                    else:
                        scale = max(0.4, min(2.4, ratio * 3.0 + 0.3))
                        label_size = max(6.0, label_size * scale)

                font_style = 'italic' if is_water else 'normal'
                alpha_val = 0.6 if is_water else 0.85
                
                txt = ax.text(text_mx, text_my, name, fontsize=label_size, fontweight='bold', fontstyle=font_style,
                              color=label_color, ha='center', va='center', alpha=alpha_val, zorder=4, clip_on=True)
                
                if not is_water:
                    txt.set_path_effects([PathEffects.withStroke(linewidth=3.0, foreground=args.map_label_outline)])
                
                # Leader lines
                if not is_water:
                    is_inside = any(p.contains_point((text_mx, text_my)) for p in paths)
                    if not is_inside and best_pt is not None:
                        ax.plot([text_mx, anchor_mx], [text_my, anchor_my], 
                                color=label_color, linestyle='--', linewidth=1.5, alpha=0.7, zorder=1)
                        ax.plot(anchor_mx, anchor_my, marker='o', color=label_color, markersize=4.0, alpha=0.8, zorder=1)
            elif gtype == "Point" and layer_type == "feature":
                import os
                mx, my = lonlat_to_merc(coords[0], coords[1])
                if merc_min_x <= mx <= merc_max_x and merc_min_y <= my <= merc_max_y:
                    f_type = props.get("type")
                    icon_path = f"icons/{f_type}.png" if f_type else None
                    if icon_path and os.path.exists(icon_path):
                        # Recolor the icon to match the map label color (which is subtle)
                        img = plt.imread(icon_path)
                        if img.shape[-1] == 4:
                            from matplotlib.colors import to_rgba
                            r, g, b, _ = to_rgba(args.map_label_color)
                            # The user wanted them subtle, maybe a bit darker than labels
                            factor = 1.2 if getattr(args, "dark_mode", False) else 0.8
                            img[:, :, 0] = min(1.0, r * factor)
                            img[:, :, 1] = min(1.0, g * factor)
                            img[:, :, 2] = min(1.0, b * factor)
                        
                        imagebox = OffsetImage(img, zoom=0.10, alpha=0.8)
                        ab = AnnotationBbox(imagebox, (mx, my), frameon=False, zorder=6)
                        ax.add_artist(ab)
                    else:
                        ax.plot(mx, my, marker='*', color=args.map_label_color, markersize=4.0, zorder=6)
                        
                    if name:
                        y_offset = (merc_max_y - merc_min_y) * 0.012
                        txt = ax.text(mx, my - y_offset, name, fontsize=5, fontweight='normal', 
                                      color=args.map_label_color, ha='center', va='top', zorder=6, clip_on=True)
                        txt.set_path_effects([PathEffects.withStroke(linewidth=1.5, foreground=args.bg_color)])
            elif gtype == "LineString" and layer_type == "feature":
                merc_coords = [lonlat_to_merc(c[0], c[1]) for c in coords]
                is_vis = any(merc_min_x <= c[0] <= merc_max_x and merc_min_y <= c[1] <= merc_max_y for c in merc_coords)
                if is_vis:
                    x = [c[0] for c in merc_coords]
                    y = [c[1] for c in merc_coords]
                    ax.plot(x, y, color=args.tick_color, linewidth=1.0, linestyle='--', alpha=0.4, zorder=5)
                    
                    if name:
                        mid_idx = len(merc_coords) // 2
                        p1, p2 = merc_coords[mid_idx-1], merc_coords[mid_idx]
                        mid_x = (p1[0] + p2[0]) / 2.0
                        mid_y = (p1[1] + p2[1]) / 2.0
                        angle = math.degrees(math.atan2(p2[1]-p1[1], p2[0]-p1[0]))
                        if angle > 90: angle -= 180
                        elif angle < -90: angle += 180
                        
                        txt = ax.text(mid_x, mid_y, name, fontsize=6, fontweight='bold', fontstyle='italic',
                                      color=args.tick_color, ha='center', va='bottom', rotation=angle, 
                                      zorder=5, clip_on=True, alpha=0.6)
                        txt.set_path_effects([PathEffects.withStroke(linewidth=2.0, foreground=args.bg_color)])
            elif gtype == "Point" and not is_water:
                mx, my = lonlat_to_merc(coords[0], coords[1])
                ax.plot(mx, my, marker='o', color=args.map_point_color, markersize=args.map_point_size)
                if name and args.show_map_labels:
                    y_offset = (merc_max_y - merc_min_y) * 0.01
                    txt = ax.text(mx, my+y_offset, name, fontsize=8, fontweight='normal', color=args.map_label_color, ha='center', va='bottom', clip_on=True)
            elif gtype == "MultiPoint" and not is_water:
                for c in coords:
                    mx, my = lonlat_to_merc(c[0], c[1])
                    ax.plot(mx, my, marker='o', color=args.map_point_color, markersize=args.map_point_size)
            
            plotted_features += 1
            
        print(f"Filtered and plotted {plotted_features} features within the map bounds.")
    except Exception as e:
        print(f"Error reading or plotting geojson: {e}")

def plot_map(points, geojson_path, args, group_colors=None):
    # Calculate bounding box of generated points
    lons = [p["lon"] for p in points]
    lats = [p["lat"] for p in points]
    
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    
    # Add margin
    margin_lon = (max_lon - min_lon) * args.margin if max_lon > min_lon else args.margin
    margin_lat = (max_lat - min_lat) * args.margin if max_lat > min_lat else args.margin
    # Ensure minimum margin
    margin_lon = max(margin_lon, args.min_margin)
    margin_lat = max(margin_lat, args.min_margin)
    
    view_bbox = (min_lon - margin_lon, min_lat - margin_lat, max_lon + margin_lon, max_lat + margin_lat)
    
    # Project view bbox to Mercator and enforce 2:1 map ratio
    merc_min_x, merc_min_y = lonlat_to_merc(view_bbox[0], view_bbox[1])
    merc_max_x, merc_max_y = lonlat_to_merc(view_bbox[2], view_bbox[3])
    
    merc_width = merc_max_x - merc_min_x
    merc_height = merc_max_y - merc_min_y
    merc_min_x = max(-MERCATOR_MAX, merc_min_x)
    merc_max_x = min(MERCATOR_MAX, merc_max_x)
    merc_min_y = max(-MERCATOR_MAX, merc_min_y)
    merc_max_y = min(MERCATOR_MAX, merc_max_y)
    
    # Update view_bbox so that MBTiles and GeoJSON filters use the padded area
    new_min_lon, new_min_lat = merc_to_lonlat(merc_min_x, merc_min_y)
    new_max_lon, new_max_lat = merc_to_lonlat(merc_max_x, merc_max_y)
    view_bbox = (new_min_lon, new_min_lat, new_max_lon, new_max_lat)
    
    # Better fonts
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Trebuchet MS', 'Verdana', 'Tahoma', 'DejaVu Sans', 'Arial', 'sans-serif']
    
    # Calculate map dimensions and target aspect ratios
    merc_width = merc_max_x - merc_min_x
    merc_height = merc_max_y - merc_min_y
    data_ratio = merc_width / merc_height if merc_height > 0 else 2.0
    
    left_margin, right_margin = 0.04, 0.96
    bottom_margin, top_margin = 0.05, 0.97
    if not getattr(args, "show_axis_ticks", True):
        left_margin, bottom_margin = 0.02, 0.02
        right_margin, top_margin = 0.98, 0.98
        
    ax_width_frac = right_margin - left_margin
    ax_height_frac = top_margin - bottom_margin
    
    if getattr(args, "fit_mode", "normal") == "dynamic":
        target_image_ratio = data_ratio / (ax_width_frac / ax_height_frac)
        h_if_w_fixed = args.width / target_image_ratio
        if h_if_w_fixed >= args.height:
            dynamic_width = args.width
            dynamic_height = h_if_w_fixed
        else:
            dynamic_height = args.height
            dynamic_width = args.height * target_image_ratio
    else:
        # normal mode: exact fixed width and height, pad map to fit
        dynamic_width = args.width
        dynamic_height = args.height
        
        target_image_ratio = args.width / args.height
        target_data_ratio = target_image_ratio * (ax_width_frac / ax_height_frac)
        
        if data_ratio < target_data_ratio:
            required_merc_width = merc_height * target_data_ratio
            padding_x = (required_merc_width - merc_width) / 2.0
            merc_min_x -= padding_x
            merc_max_x += padding_x
        else:
            required_merc_height = merc_width / target_data_ratio
            padding_y = (required_merc_height - merc_height) / 2.0
            merc_min_y -= padding_y
            merc_max_y += padding_y
            
        merc_min_x = max(-MERCATOR_MAX, merc_min_x)
        merc_max_x = min(MERCATOR_MAX, merc_max_x)
        merc_min_y = max(-MERCATOR_MAX, merc_min_y)
        merc_max_y = min(MERCATOR_MAX, merc_max_y)
        
        # update view bbox based on padded area
        new_min_lon, new_min_lat = merc_to_lonlat(merc_min_x, merc_min_y)
        new_max_lon, new_max_lat = merc_to_lonlat(merc_max_x, merc_max_y)
        view_bbox = (new_min_lon, new_min_lat, new_max_lon, new_max_lat)
        
    args.width = dynamic_width
    args.height = dynamic_height
    
    fig, ax = plt.subplots(figsize=(args.width, args.height))
    fig.subplots_adjust(left=left_margin, right=right_margin, bottom=bottom_margin, top=top_margin)
    # Aspect ratio is simply equal for Mercator
    ax.set_aspect('equal')
    fig_bg = "#11151c" if args.dark_mode else "white"
    fig.patch.set_facecolor(fig_bg)
    ax.set_facecolor(args.bg_color)
    ax.patch.set_zorder(-1)
    
        
    # Read geojson layers
    merc_bounds = (merc_min_x, merc_min_y, merc_max_x, merc_max_y)
    
    if geojson_path:
        print(f"Loading map data from {geojson_path}...")
        plot_geojson_layer(geojson_path, view_bbox, ax, args, merc_bounds, layer_type="land")
        
    if getattr(args, "water_data", None):
        print(f"Loading water data from {args.water_data}...")
        plot_geojson_layer(args.water_data, view_bbox, ax, args, merc_bounds, layer_type="water")
        
    if getattr(args, "rivers_data", None):
        import os
        if os.path.exists(args.rivers_data):
            print(f"Loading rivers data from {args.rivers_data}...")
            plot_geojson_layer(args.rivers_data, view_bbox, ax, args, merc_bounds, layer_type="river")
            
    if getattr(args, "features_data", None):
        import os
        if os.path.exists(args.features_data):
            lon_span = new_max_lon - new_min_lon
            map_zoom = 0
            if lon_span > 0:
                target_tiles = 4.0
                map_zoom = int(round(math.log2(360.0 * target_tiles / lon_span)))
                map_zoom = max(0, map_zoom)
                
            if map_zoom >= args.features_min_zoom:
                print(f"Loading features data from {args.features_data} (zoom level {map_zoom} >= {args.features_min_zoom})...")
                plot_geojson_layer(args.features_data, view_bbox, ax, args, merc_bounds, layer_type="feature")
            else:
                print(f"Skipping features data (zoom level {map_zoom} < {args.features_min_zoom}).")
    
    # Plot generated points
    for i, p in enumerate(points):
        lon, lat = p["lon"], p["lat"]
        mx, my = lonlat_to_merc(lon, lat)
        
        color = args.point_color
        if group_colors and p.get("group") in group_colors:
            color = group_colors[p["group"]]
            
        ax.plot(mx, my, marker=args.marker, color=color, markersize=args.point_size, markeredgecolor='black', markeredgewidth=1.0, zorder=5)
        # Label generated points
        if args.show_labels and p.get('name'):
            label = p['name']
            if not getattr(args, "csv", "") and 'value' in p and p['value']:
                label += f"\n(v:{p['value']})"
            y_offset = (merc_max_y - merc_min_y) * 0.015
            txt = ax.text(mx, my + y_offset, label, fontsize=8, fontweight='normal', color=args.label_color, ha='center', va='bottom', zorder=6, clip_on=True)
            txt.set_path_effects([PathEffects.withStroke(linewidth=1.0, foreground=args.label_outline)])
    

    # Add Scale Bar
    center_lat = (args.lat_min + args.lat_max) / 2.0
    lon_span = new_max_lon - new_min_lon
    view_width_m = lon_span * math.cos(math.radians(center_lat)) * 111320
    view_width_nm = view_width_m / 1852.0
    
    target_scale_nm = view_width_nm * 0.10
    magnitude = 10 ** math.floor(math.log10(max(1, target_scale_nm))) if target_scale_nm > 0 else 1
    normalized = target_scale_nm / magnitude
    if normalized < 2: nice_val = 1
    elif normalized < 5: nice_val = 2
    else: nice_val = 5
    scale_nm = max(1, int(nice_val * magnitude))
    
    scale_label = f"{scale_nm} NM"
    deg_span = (scale_nm * 1852.0) / (math.cos(math.radians(center_lat)) * 111320)
    merc_span = deg_span * MERCATOR_MAX / 180.0
    
    sb_color = "#7f8c8d" if not getattr(args, "dark_mode", False) else "#b2bec3"
    
    # Bottom right corner for scale bar (tucked closer to edge: 0.5%)
    sb_x = merc_max_x - (merc_max_x - merc_min_x) * 0.005
    sb_y = merc_min_y + (merc_max_y - merc_min_y) * 0.025
    
    ax.plot([sb_x - merc_span, sb_x], [sb_y, sb_y], color=sb_color, linewidth=1.2, zorder=10)
    ax.plot([sb_x - merc_span, sb_x - merc_span], [sb_y - (merc_max_y - merc_min_y)*0.003, sb_y + (merc_max_y - merc_min_y)*0.003], color=sb_color, linewidth=1.0, zorder=10)
    ax.plot([sb_x, sb_x], [sb_y - (merc_max_y - merc_min_y)*0.003, sb_y + (merc_max_y - merc_min_y)*0.003], color=sb_color, linewidth=1.0, zorder=10)
    ax.text(sb_x - merc_span/2, sb_y + (merc_max_y - merc_min_y)*0.004, scale_label, fontsize=8, fontweight='bold', color=sb_color, ha='center', va='bottom', zorder=10)

    # Scale Ratio text centered directly under the scale bar
    scale_ratio = int(view_width_m / (args.width * 0.0254))
    text_y = merc_min_y + (merc_max_y - merc_min_y) * 0.006
    ax.text(sb_x - merc_span/2, text_y, f"Scale 1:{scale_ratio:,}", fontsize=8, fontweight='bold', color=sb_color, ha='center', va='bottom', zorder=10)

    # Add Legend
    legend_elements = []
    if group_colors:
        for g in sorted(group_colors.keys()):
            legend_elements.append(mlines.Line2D([0], [0], linestyle='none', marker=args.marker, color='w', markerfacecolor=group_colors[g], markersize=8, markeredgecolor='black', label=g))
    elif not getattr(args, "csv", ""):
        legend_elements.append(mlines.Line2D([0], [0], linestyle='none', marker=args.marker, color='w', markerfacecolor=args.point_color, markersize=8, markeredgecolor='black', label='Generated Points'))
        
    if legend_elements:
        ax.legend(handles=legend_elements, loc='lower left', bbox_to_anchor=(0.005, 0.006), borderaxespad=0, fontsize=9, framealpha=0.85, facecolor=args.bg_color, edgecolor=args.map_border, labelcolor=args.label_color)

    ax.set_xlim(merc_min_x, merc_max_x)
    ax.set_ylim(merc_min_y, merc_max_y)
    
    if args.show_axis_ticks:
        ax.grid(True, linestyle='--', alpha=0.4, color=args.map_border)
        ax.set_xlabel("Longitude", fontsize=10, fontweight='bold', color=args.tick_color)
        ax.set_ylabel("Latitude", fontsize=10, fontweight='bold', color=args.tick_color)
        
        @ticker.FuncFormatter
        def lon_formatter(x, pos):
            lon, _ = merc_to_lonlat(x, 0)
            return f"{lon:.1f}°"

        @ticker.FuncFormatter
        def lat_formatter(y, pos):
            _, lat = merc_to_lonlat(0, y)
            return f"{lat:.1f}°"

        ax.xaxis.set_major_formatter(lon_formatter)
        ax.yaxis.set_major_formatter(lat_formatter)
        ax.xaxis.set_major_locator(plt.MaxNLocator(7))
        ax.yaxis.set_major_locator(plt.MaxNLocator(7))
        ax.tick_params(axis='both', labelsize=8, colors=args.tick_color)
    else:
        # Make it look like a map by removing standard axes
        ax.set_xticks([])
        ax.set_yticks([])
        
    for spine in ax.spines.values():
        spine.set_edgecolor(args.map_border)
        spine.set_linewidth(2)
        
    if args.title:
        plt.title(args.title, fontsize=18, fontweight='bold', color='#2c3e50', pad=20)
    plt.savefig(args.output, dpi=args.dpi)
    print(f"Map successfully saved to {args.output}")

def main():
    import os
    PKG_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

    parser = argparse.ArgumentParser(description="Generate lat/lon points and plot them on a map using local GeoJSON.")
    
    # Input/Output
    parser.add_argument("-o", "--output", type=str, default="/tmp/map.png", help="Output image filename")
    parser.add_argument("--geojson", type=str, default=os.path.join(PKG_DATA_DIR, "world.geojson"), help="Path to GeoJSON file.")
    parser.add_argument("--water-data", type=str, default=os.path.join(PKG_DATA_DIR, "water.geojson"), help="Path to water GeoJSON file")
    parser.add_argument("--rivers-data", type=str, default=os.path.join(PKG_DATA_DIR, "rivers.geojson"), help="Path to rivers GeoJSON file")
    parser.add_argument("--features-data", type=str, default=os.path.join(PKG_DATA_DIR, "features.geojson"), help="Path to features GeoJSON file")
    parser.add_argument("--features-min-zoom", type=int, default=6, help="Minimum zoom level to display features (0=world, higher=closer)")
    
    # Point Generation
    parser.add_argument("--csv", type=str, default="", help="Path to CSV file with points")
    parser.add_argument("--csv-lat", type=str, default="", help="CSV latitude column")
    parser.add_argument("--csv-lon", type=str, default="", help="CSV longitude column")
    parser.add_argument("--csv-label", type=str, default="", help="CSV label column")
    parser.add_argument("--csv-group", type=str, default="", help="CSV group column")
    parser.add_argument("-n", "--num-points", type=int, default=15, help="Number of points to generate")
    parser.add_argument("--lat-min", type=float, default=None, help="Min latitude for point generation")
    parser.add_argument("--lat-max", type=float, default=None, help="Max latitude for point generation")
    parser.add_argument("--lon-min", type=float, default=None, help="Min longitude for point generation")
    parser.add_argument("--lon-max", type=float, default=None, help="Max longitude for point generation")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for point generation")
    
    # Map Styling
    parser.add_argument("--margin", type=float, default=0.1, help="Margin around points (fraction of width/height)")
    parser.add_argument("--min-margin", type=float, default=1.0, help="Minimum margin in degrees")
    parser.add_argument("--width", type=float, default=20.0, help="Image width in inches")
    parser.add_argument("--height", type=float, default=10.0, help="Image height in inches")
    parser.add_argument("--fit-mode", choices=["normal", "dynamic"], default="normal", help="Fit mode: 'normal' fixes map to exact width/height, 'dynamic' expands to fit data.")
    parser.add_argument("--dpi", type=int, default=100, help="Output image DPI")
    parser.add_argument("--title", type=str, default="", help="Map title")
    
    # Colors
    parser.add_argument("--bg-color", type=str, default="#e0f3f8", help="Background color (ocean/empty area)")
    parser.add_argument("--map-fill", type=str, default="#fefee9", help="Map polygon fill color")
    parser.add_argument("--map-border", type=str, default="#7f8c8d", help="Map polygon border color")
    parser.add_argument("--border-width", type=float, default=1.0, help="Map border width")
    parser.add_argument("--point-color", type=str, default="#e74c3c", help="Generated points color")
    parser.add_argument("--point-size", type=float, default=8.0, help="Generated points size")
    parser.add_argument("--marker", type=str, default="o", help="Generated points marker style")
    parser.add_argument("--label-color", type=str, default="black", help="Label text color")
    parser.add_argument("--label-outline", type=str, default="white", help="Label outline color")
    parser.add_argument("--tick-color", type=str, default="black", help="Axis tick and label color")
    
    # Map Points
    parser.add_argument("--map-point-color", type=str, default="#95a5a6", help="Map data points color")
    parser.add_argument("--map-point-size", type=float, default=4.0, help="Map data points size")
    parser.add_argument("--map-label-color", type=str, default="#2980b9", help="Map data labels color")
    parser.add_argument("--map-label-size", type=float, default=15.0, help="Map data labels size")
    parser.add_argument("--map-label-outline", type=str, default="white", help="Map data labels outline color")
    parser.add_argument("--water-label-color", type=str, default="#95c5d8", help="Water body label color")
    parser.add_argument("--water-label-size", type=float, default=26.0, help="Water body label size")
    parser.add_argument("--no-map-labels", dest="show_map_labels", action="store_false", help="Hide labels for map data points and polygons")
    parser.add_argument("--no-labels", dest="show_labels", action="store_false", help="Hide labels for generated points")
    parser.add_argument("--no-axis-ticks", dest="show_axis_ticks", action="store_false", help="Hide lat/lon axis ticks")
    parser.add_argument("--dark-mode", action="store_true", help="Use dark mode color scheme")
    
    args = parser.parse_args()
    
    if args.dark_mode:
        if args.bg_color == "#e0f3f8": args.bg_color = "#1a252c"
        if args.map_fill == "#fefee9": args.map_fill = "#2d3436"
        if args.map_border == "#7f8c8d": args.map_border = "#576574"
        if args.point_color == "#e74c3c": args.point_color = "#ff7675"
        if args.label_color == "black": args.label_color = "white"
        if args.label_outline == "white": args.label_outline = "black"
        if args.tick_color == "black": args.tick_color = "#b2bec3"
        if args.map_point_color == "#95a5a6": args.map_point_color = "#636e72"
        if args.map_label_color == "#2980b9": args.map_label_color = "#7f8c8d" # subtle gray fill
        if args.map_label_outline == "white": args.map_label_outline = "#2d3436" # outline matches land to hide it
        if args.water_label_color == "#95c5d8": args.water_label_color = "#2c3e50"
        if args.map_label_size == 15.0: args.map_label_size = 11.0
    
    # Find geojson if not specified
    geojson_path = args.geojson
    if not geojson_path or not os.path.exists(geojson_path):
        print(f"Warning: Base map geojson file not found at {geojson_path}. Map may not render background.")
            
            
    # Generate or Load points
    points = []
    groups_present = set()
    group_colors = {}
    
    if args.csv:
        print(f"Loading points from {args.csv}...")
        with open(args.csv, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = [h.lower() for h in reader.fieldnames] if reader.fieldnames else []
            lat_col = args.csv_lat if args.csv_lat else next((h for h in reader.fieldnames if h.lower() in ('lat', 'latitude')), None)
            lon_col = args.csv_lon if args.csv_lon else next((h for h in reader.fieldnames if h.lower() in ('lon', 'longitude', 'lng')), None)
            lbl_col = args.csv_label if args.csv_label else next((h for h in reader.fieldnames if h.lower() in ('label', 'name', 'site', 'title')), None)
            grp_col = args.csv_group if args.csv_group else next((h for h in reader.fieldnames if h.lower() in ('group', 'category', 'type')), None)
            
            if not lat_col or not lon_col:
                print("Error: Could not determine latitude and longitude columns in CSV.")
                sys.exit(1)
                
            for row in reader:
                try:
                    lat = float(row[lat_col])
                    lon = float(row[lon_col])
                    name = row[lbl_col] if lbl_col and lbl_col in row else ""
                    group = row[grp_col] if grp_col and grp_col in row else ""
                    points.append({"lon": lon, "lat": lat, "name": name, "value": 0, "group": group})
                    if group:
                        groups_present.add(group)
                except (ValueError, KeyError):
                    continue
        if points:
            lons = [p["lon"] for p in points]
            lats = [p["lat"] for p in points]
            # Ensure we don't accidentally restrict bounds if the user specified them
            if args.lat_min is None: args.lat_min = min(lats)
            if args.lat_max is None: args.lat_max = max(lats)
            if args.lon_min is None: args.lon_min = min(lons)
            if args.lon_max is None: args.lon_max = max(lons)
            
        if groups_present:
            cmap = cm.get_cmap('Set3')
            colors = [matplotlib.colors.to_hex(cmap(i/11.0)) for i in range(12)]
            for i, g in enumerate(sorted(groups_present)):
                group_colors[g] = colors[i % len(colors)]
    else:
        if args.seed is not None:
            random.seed(args.seed)
            
        if args.lat_min is None or args.lat_max is None or args.lon_min is None or args.lon_max is None:
            center_lat = random.uniform(-40, 50)
            center_lon = random.uniform(-100, 100)
            lat_spread = random.uniform(5, 15)
            lon_spread = random.uniform(5, 15)
            args.lat_min = center_lat - lat_spread / 2.0
            args.lat_max = center_lat + lat_spread / 2.0
            args.lon_min = center_lon - lon_spread / 2.0
            args.lon_max = center_lon + lon_spread / 2.0
            print(f"Random region selected: Lat [{args.lat_min:.2f}, {args.lat_max:.2f}], Lon [{args.lon_min:.2f}, {args.lon_max:.2f}]")
        points = generate_points(args.num_points, args.lat_min, args.lat_max, args.lon_min, args.lon_max)

    
    # Plot
    plot_map(points, geojson_path, args, group_colors)

if __name__ == "__main__":
    main()
