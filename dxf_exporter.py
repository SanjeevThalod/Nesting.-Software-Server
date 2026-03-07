"""
DXF Exporter - Exports nested layout to DXF format
"""

import ezdxf
from ezdxf import colors
from typing import List
from nesting_algorithm import NestedShape
import math


class DXFExporter:
    def __init__(self, filename: str, sheet_width: float, sheet_height: float):
        """
        Initialize DXF exporter
        
        Args:
            filename: Output DXF file path
            sheet_width: Width of the material sheet in mm
            sheet_height: Height of the material sheet in mm
        """
        self.filename = filename
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.doc = ezdxf.new('R2010')
        self.msp = self.doc.modelspace()
        
    def add_sheet_outline(self, line_width: float = 0.5):
        """Add the material sheet outline"""
        if "SHEET" not in [l.dxf.name for l in self.doc.layers]:
            self.doc.layers.new(name="SHEET", dxfattribs={'color': colors.GREEN})
            
        points = [
            (0, 0),
            (self.sheet_width, 0),
            (self.sheet_width, self.sheet_height),
            (0, self.sheet_height),
            (0, 0)
        ]
        self.msp.add_lwpolyline(points, close=True, dxfattribs={'layer': "SHEET"})
        
    def add_nested_shapes(self, nested_shapes: List[NestedShape]):
        """Add all nested shapes to DXF"""
        for i, nested in enumerate(nested_shapes):
            layer_name = f"PART_{i+1}"
            if layer_name not in [l.dxf.name for l in self.doc.layers]:
                self.doc.layers.new(name=layer_name, dxfattribs={'color': colors.BLUE})
            
            shape = nested.original_shape
            
            if shape.shape_type == "rectangle":
                self._add_rotated_rectangle(nested, layer_name)
            elif shape.shape_type == "circle":
                self._add_rotated_circle(nested, layer_name)
            elif shape.shape_type == "point":
                self._add_point(nested, layer_name)
            else:
                self._add_rotated_polyline(nested, layer_name)
    
    def _get_local_points(self, shape) -> List[tuple]:
        """Get shape points in local coordinates (relative to shape's bounding box origin)."""
        if not shape.points:
            return [(0, 0), (shape.width, 0), (shape.width, shape.height), (0, shape.height)]
        bb = shape.bounding_box
        if not bb or len(bb) < 4:
            return list(shape.points)
        min_x, min_y = bb[0], bb[1]
        return [(float(px) - min_x, float(py) - min_y) for px, py in shape.points]

    def _get_shape_origin(self, shape) -> tuple:
        """Get absolute DXF origin (min corner) of the shape for converting holes to local coords."""
        origin = getattr(shape, 'origin', None)
        if origin is not None and len(origin) >= 2:
            return (float(origin[0]), float(origin[1]))
        bb = shape.bounding_box
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

    def _add_rotated_rectangle(self, nested: NestedShape, layer: str):
        """Add rotated rectangle"""
        shape = nested.original_shape
        x, y = nested.x, nested.y
        
        # Get points in local coordinates (relative to shape origin)
        points = self._get_local_points(shape)[:4]
        if len(points) < 4:
            points = [(0, 0), (shape.width, 0), (shape.width, shape.height), (0, shape.height)]
        
        # Transform to sheet coordinates
        transformed = self._transform_points(points, x, y, nested.rotation)
        self.msp.add_lwpolyline(transformed, close=True, dxfattribs={'layer': layer})
        # Add holes
        self._add_holes(nested, layer)
    
    def _add_rotated_circle(self, nested: NestedShape, layer: str):
        """Add rotated circle (circles don't rotate, just move)"""
        shape = nested.original_shape
        cx = nested.x + nested.width/2
        cy = nested.y + nested.height/2
        self.msp.add_circle((cx, cy), shape.radius, dxfattribs={'layer': layer})
    
    def _add_rotated_polyline(self, nested: NestedShape, layer: str):
        """Add rotated polyline"""
        shape = nested.original_shape
        local_points = self._get_local_points(shape)
        if not local_points:
            return
        transformed = self._transform_points(local_points, nested.x, nested.y, nested.rotation)
        self.msp.add_lwpolyline(transformed, close=True, dxfattribs={'layer': layer})
        # Add holes
        self._add_holes(nested, layer)

    def _add_holes(self, nested: NestedShape, layer: str):
        """Add hole contours for a shape (rectangle or polyline). Circle holes as circles, others as polylines."""
        shape = nested.original_shape
        holes = getattr(shape, 'holes', None) or []
        for hole in holes:
            if isinstance(hole, dict) and hole.get("type") == "circle":
                local_center = self._get_local_circle_hole_center(shape, hole)
                if local_center is None:
                    continue
                radius = float(hole.get("radius", 0))
                if radius <= 0:
                    continue
                # Transform center by nested position and rotation
                transformed_center = self._transform_points([local_center], nested.x, nested.y, nested.rotation)[0]
                self.msp.add_circle(transformed_center, radius, dxfattribs={'layer': layer})
                continue
            if not hole or len(hole) < 3:
                continue
            local_hole = self._get_local_hole_points(shape, hole)
            if not local_hole:
                continue
            transformed = self._transform_points(local_hole, nested.x, nested.y, nested.rotation)
            self.msp.add_lwpolyline(transformed, close=True, dxfattribs={'layer': layer})

    def _add_point(self, nested: NestedShape, layer: str, point_radius: float = 1.0):
        """Add a point as a small circle"""
        shape = nested.original_shape
        # Center in local coords relative to bounding box; then add nested position
        bb = shape.bounding_box
        if bb and len(bb) >= 4:
            local_cx = shape.center[0] - bb[0]
            local_cy = shape.center[1] - bb[1]
        else:
            local_cx, local_cy = shape.center[0], shape.center[1]
        cx = nested.x + local_cx
        cy = nested.y + local_cy
        self.msp.add_circle((cx, cy), point_radius, dxfattribs={'layer': layer, 'color': colors.RED})
    
    def _transform_points(self, points: List[tuple], x: float, y: float, rotation: float) -> List[tuple]:
        """Transform points by translation and rotation"""
        if rotation == 0:
            return [(px + x, py + y) for px, py in points]
        
        rad = math.radians(rotation)
        cos_r, sin_r = math.cos(rad), math.sin(rad)
        
        transformed = []
        for px, py in points:
            # Rotate around origin
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            # Translate
            transformed.append((rx + x, ry + y))
        
        return transformed
    
    def save(self):
        """Save the DXF file"""
        self.doc.saveas(self.filename)
        print(f"✓ DXF file saved: {self.filename}")
