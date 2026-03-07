"""
NC (G-code) Exporter - Exports nested layout to G-code format
"""

from typing import List
from nesting_algorithm import NestedShape
import math


class NCExporter:
    def __init__(self, filename: str, 
                 feed_rate: float = 1000.0,
                 plunge_rate: float = 300.0,
                 safe_height: float = 10.0,
                 cut_depth: float = -5.0,
                 tool_diameter: float = 6.0):
        """
        Initialize NC/G-code exporter
        
        Args:
            filename: Output NC file path
            feed_rate: Cutting feed rate in mm/min
            plunge_rate: Plunge feed rate in mm/min
            safe_height: Safe Z height for rapid moves in mm
            cut_depth: Cutting depth (negative value) in mm
            tool_diameter: Tool diameter in mm
        """
        self.filename = filename
        self.feed_rate = feed_rate
        self.plunge_rate = plunge_rate
        self.safe_height = safe_height
        self.cut_depth = cut_depth
        self.tool_diameter = tool_diameter
        self.lines = []
        
    def header(self, program_name: str = "NESTING_PROGRAM"):
        """Add G-code header"""
        self.lines.append(f"({program_name})")
        self.lines.append("G21 ; Set units to millimeters")
        self.lines.append("G90 ; Absolute positioning")
        self.lines.append("G17 ; XY plane selection")
        self.lines.append("G94 ; Feed rate per minute")
        self.lines.append(f"G00 Z{self.safe_height:.3f} ; Rapid to safe height")
        self.lines.append("")
        
    def footer(self):
        """Add G-code footer"""
        self.lines.append("")
        self.lines.append(f"G00 Z{self.safe_height:.3f} ; Rapid to safe height")
        self.lines.append("G00 X0 Y0 ; Return to origin")
        self.lines.append("M30 ; End of program")
        
    def _get_local_points(self, shape) -> List[tuple]:
        """Get shape points in local coordinates (relative to shape's bounding box origin)."""
        if not shape.points:
            return []
        bb = getattr(shape, 'bounding_box', None)
        if not bb or len(bb) < 4:
            return list(shape.points)
        min_x, min_y = bb[0], bb[1]
        return [(float(px) - min_x, float(py) - min_y) for px, py in shape.points]

    def _get_shape_origin(self, shape) -> tuple:
        """Get absolute DXF origin (min corner) of the shape for converting holes to local coords."""
        origin = getattr(shape, 'origin', None)
        if origin is not None and len(origin) >= 2:
            return (float(origin[0]), float(origin[1]))
        bb = getattr(shape, 'bounding_box', None)
        if bb and len(bb) >= 4:
            return (float(bb[0]), float(bb[1]))
        return (0.0, 0.0)

    def _get_local_hole_points(self, shape, hole: List[tuple]) -> List[tuple]:
        """Get hole points in local coordinates (relative to shape origin)."""
        if not hole:
            return []
        ox, oy = self._get_shape_origin(shape)
        return [(float(px) - ox, float(py) - oy) for px, py in hole]

    def _get_local_circle_hole_center(self, shape, hole: dict) -> tuple:
        """Get circle hole center in local coordinates (relative to shape origin)."""
        if not hole or hole.get("type") != "circle":
            return None
        center = hole.get("center")
        if not center or len(center) < 2:
            return None
        ox, oy = self._get_shape_origin(shape)
        return (float(center[0]) - ox, float(center[1]) - oy)

    def add_nested_shapes(self, nested_shapes: List[NestedShape]):
        """Add all nested shapes to G-code"""
        if not nested_shapes:
            return
        for nested in nested_shapes:
            shape = nested.original_shape
            try:
                if shape.shape_type == "rectangle":
                    self._cut_rotated_rectangle(nested)
                elif shape.shape_type == "circle":
                    self._cut_circle(nested)
                elif shape.shape_type == "point":
                    self._drill_point(nested)
                else:
                    self._cut_rotated_polyline(nested)
            except Exception as e:
                self.lines.append(f"(Error outputting shape {getattr(shape, 'shape_id', '?')}: {e})")
    
    def _cut_rotated_rectangle(self, nested: NestedShape):
        """Cut rotated rectangle"""
        shape = nested.original_shape
        points = self._get_local_points(shape)
        if len(points) < 4:
            points = [(0, 0), (shape.width, 0), (shape.width, shape.height), (0, shape.height)]
        else:
            points = points[:4]
        transformed = self._transform_points(points, nested.x, nested.y, nested.rotation)
        
        self.lines.append(f"(Cutting {shape.shape_id} at {nested.x:.2f}, {nested.y:.2f}, rotation {nested.rotation:.1f}°)")
        self.lines.append(f"G00 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f}")
        self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
        
        for point in transformed[1:]:
            self.lines.append(f"G01 X{point[0]:.3f} Y{point[1]:.3f} F{self.feed_rate:.1f}")
        
        # Close the path
        self.lines.append(f"G01 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f} F{self.feed_rate:.1f}")
        self.lines.append(f"G00 Z{self.safe_height:.3f}")
        self.lines.append("")
        # Cut holes
        self._cut_holes(nested)
    
    def _cut_circle(self, nested: NestedShape):
        """Cut circle"""
        shape = nested.original_shape
        cx = nested.x + nested.width/2
        cy = nested.y + nested.height/2
        
        self.lines.append(f"(Cutting circle {shape.shape_id} at {cx:.2f}, {cy:.2f})")
        self.lines.append(f"G00 X{cx + shape.radius:.3f} Y{cy:.3f}")
        self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
        
        # Cut full circle using G02
        self.lines.append(f"G02 X{cx + shape.radius:.3f} Y{cy:.3f} I{-shape.radius:.3f} J0 F{self.feed_rate:.1f}")
        self.lines.append(f"G00 Z{self.safe_height:.3f}")
        self.lines.append("")
    
    def _cut_rotated_polyline(self, nested: NestedShape):
        """Cut rotated polyline"""
        shape = nested.original_shape
        local_points = self._get_local_points(shape)
        if not local_points:
            self.lines.append(f"(Skip {getattr(shape, 'shape_id', '?')}: no points)")
            return
        transformed = self._transform_points(local_points, nested.x, nested.y, nested.rotation)
        
        self.lines.append(f"(Cutting {shape.shape_id} polyline)")
        self.lines.append(f"G00 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f}")
        self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
        
        for point in transformed[1:]:
            self.lines.append(f"G01 X{point[0]:.3f} Y{point[1]:.3f} F{self.feed_rate:.1f}")
        
        # Close if needed
        if transformed[0] != transformed[-1]:
            self.lines.append(f"G01 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f} F{self.feed_rate:.1f}")
        
        self.lines.append(f"G00 Z{self.safe_height:.3f}")
        self.lines.append("")
        # Cut holes
        self._cut_holes(nested)

    def _cut_holes(self, nested: NestedShape):
        """Cut hole contours for a shape. Circle holes use G02; polyline holes use G01."""
        shape = nested.original_shape
        holes = getattr(shape, 'holes', None) or []
        for idx, hole in enumerate(holes):
            if isinstance(hole, dict) and hole.get("type") == "circle":
                local_center = self._get_local_circle_hole_center(shape, hole)
                if local_center is None:
                    continue
                radius = float(hole.get("radius", 0))
                if radius <= 0:
                    continue
                transformed_center = self._transform_points([local_center], nested.x, nested.y, nested.rotation)[0]
                cx, cy = transformed_center[0], transformed_center[1]
                self.lines.append(f"(Cutting circular hole {idx + 1} of {shape.shape_id})")
                self.lines.append(f"G00 X{cx + radius:.3f} Y{cy:.3f}")
                self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
                self.lines.append(f"G02 X{cx + radius:.3f} Y{cy:.3f} I{-radius:.3f} J0 F{self.feed_rate:.1f}")
                self.lines.append(f"G00 Z{self.safe_height:.3f}")
                self.lines.append("")
                continue
            if not hole or len(hole) < 3:
                continue
            local_hole = self._get_local_hole_points(shape, hole)
            if not local_hole:
                continue
            transformed = self._transform_points(local_hole, nested.x, nested.y, nested.rotation)
            self.lines.append(f"(Cutting hole {idx + 1} of {shape.shape_id})")
            self.lines.append(f"G00 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f}")
            self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
            for point in transformed[1:]:
                self.lines.append(f"G01 X{point[0]:.3f} Y{point[1]:.3f} F{self.feed_rate:.1f}")
            if transformed[0] != transformed[-1]:
                self.lines.append(f"G01 X{transformed[0][0]:.3f} Y{transformed[0][1]:.3f} F{self.feed_rate:.1f}")
            self.lines.append(f"G00 Z{self.safe_height:.3f}")
            self.lines.append("")

    def _drill_point(self, nested: NestedShape):
        """Perform a drilling operation for a point shape"""
        shape = nested.original_shape
        bb = getattr(shape, 'bounding_box', None)
        if bb and len(bb) >= 4:
            local_cx = shape.center[0] - bb[0]
            local_cy = shape.center[1] - bb[1]
        else:
            local_cx, local_cy = shape.center[0], shape.center[1]
        cx = nested.x + local_cx
        cy = nested.y + local_cy
        
        self.lines.append(f"(Drilling point {shape.shape_id} at {cx:.3f}, {cy:.3f})")
        self.lines.append(f"G00 X{cx:.3f} Y{cy:.3f}")
        self.lines.append(f"G01 Z{self.cut_depth:.3f} F{self.plunge_rate:.1f}")
        self.lines.append(f"G00 Z{self.safe_height:.3f}")
        self.lines.append("")
    
    def _transform_points(self, points: List[tuple], x: float, y: float, rotation: float) -> List[tuple]:
        """Transform points by translation and rotation"""
        if rotation == 0:
            return [(px + x, py + y) for px, py in points]
        
        rad = math.radians(rotation)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        
        transformed = []
        for px, py in points:
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            transformed.append((rx + x, ry + y))
        
        return transformed
    
    def spindle_on(self, speed: int = 18000):
        """Spindle on command"""
        self.lines.append(f"M03 S{speed} ; Spindle on clockwise")
        
    def spindle_off(self):
        """Spindle off command"""
        self.lines.append("M05 ; Spindle off")
        
    def save(self):
        """Save the NC file"""
        with open(self.filename, 'w') as f:
            f.write('\n'.join(self.lines))
        print(f"✓ NC file saved: {self.filename}")
