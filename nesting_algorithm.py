"""
Advanced Nesting Algorithm - Minimizes sheet waste
Uses Bottom-Left Fill algorithm with rotation support
"""

from typing import List, Tuple, Optional
import math
from dxf_reader import Shape


class NestedShape:
    """Represents a shape placed on the sheet"""
    def __init__(self, shape: Shape, x: float, y: float, rotation: float = 0.0):
        self.original_shape = shape
        self.x = x
        self.y = y
        self.rotation = rotation
        self.width = shape.width
        self.height = shape.height
        
        # Calculate rotated dimensions
        if rotation != 0:
            rad = math.radians(rotation)
            cos_r = abs(math.cos(rad))
            sin_r = abs(math.sin(rad))
            self.width = shape.width * cos_r + shape.height * sin_r
            self.height = shape.width * sin_r + shape.height * cos_r
        
    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Get bounding box (min_x, min_y, max_x, max_y)"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)
    
    def overlaps(self, other: 'NestedShape', margin: float = 0.0) -> bool:
        """Check if this shape overlaps with another"""
        self_bounds = self.get_bounds()
        other_bounds = other.get_bounds()
        
        # Check rectangle overlap
        return not (
            self_bounds[2] + margin <= other_bounds[0] or  # self right <= other left
            self_bounds[0] >= other_bounds[2] + margin or  # self left >= other right
            self_bounds[3] + margin <= other_bounds[1] or  # self top <= other bottom
            self_bounds[1] >= other_bounds[3] + margin     # self bottom >= other top
        )


class NestingAlgorithm:
    """Advanced nesting algorithm to minimize waste"""
    
    def __init__(self, sheet_width: float, sheet_height: float, 
                 margin: float = 0.0, allow_rotation: bool = True):
        """
        Initialize nesting algorithm
        
        Args:
            sheet_width: Width of the material sheet
            sheet_height: Height of the material sheet
            margin: Minimum margin between parts (in mm)
            allow_rotation: Whether to try rotated orientations
        """
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.margin = margin
        self.allow_rotation = allow_rotation
        self.nested_shapes: List[NestedShape] = []
        
    def nest(self, shapes: List[Shape]) -> Tuple[List[NestedShape], float]:
        """
        Nest shapes on the sheet
        
        Args:
            shapes: List of shapes to nest
            
        Returns:
            Tuple of (nested_shapes, utilization_percentage)
        """
        # Sort shapes by area (largest first) for better packing
        sorted_shapes = sorted(shapes, key=lambda s: s.area, reverse=True)
        
        self.nested_shapes = []
        
        for shape in sorted_shapes:
            placed = False
            
            # Try different rotations if allowed
            rotations = [0.0]
            if self.allow_rotation:
                rotations = [0.0, 90.0, 180.0, 270.0]
            
            for rotation in rotations:
                nested = self._try_place_shape(shape, rotation)
                if nested:
                    self.nested_shapes.append(nested)
                    placed = True
                    break
            
            if not placed:
                print(f"Warning: Could not place shape {shape.shape_id}")
        
        # Calculate utilization
        total_area = sum(s.area for s in sorted_shapes)
        used_area = sum(n.width * n.height for n in self.nested_shapes)
        sheet_area = self.sheet_width * self.sheet_height
        utilization = (used_area / sheet_area * 100) if sheet_area > 0 else 0
        
        return self.nested_shapes, utilization
    
    def _try_place_shape(self, shape: Shape, rotation: float) -> Optional[NestedShape]:
        """Try to place a shape at the best position using Bottom-Left Fill"""
        # Calculate rotated dimensions
        if rotation != 0:
            rad = math.radians(rotation)
            cos_r = abs(math.cos(rad))
            sin_r = abs(math.sin(rad))
            width = shape.width * cos_r + shape.height * sin_r
            height = shape.width * sin_r + shape.height * cos_r
        else:
            width = shape.width
            height = shape.height
        
        # Check if shape fits on sheet
        if width + 2 * self.margin > self.sheet_width or \
           height + 2 * self.margin > self.sheet_height:
            return None
        
        # Try bottom-left fill positions
        best_x = None
        best_y = None
        best_score = float('inf')
        
        # Generate candidate positions
        candidates = self._generate_candidate_positions(width, height)
        
        for x, y in candidates:
            if x + width + self.margin > self.sheet_width or \
               y + height + self.margin > self.sheet_height:
                continue
            
            # Check for collisions
            test_shape = NestedShape(shape, x, y, rotation)
            test_shape.width = width
            test_shape.height = height
            
            if not self._has_collision(test_shape):
                # Score: prefer lower and more left positions
                score = y * 1000 + x
                if score < best_score:
                    best_score = score
                    best_x = x
                    best_y = y
        
        if best_x is not None and best_y is not None:
            nested = NestedShape(shape, best_x, best_y, rotation)
            nested.width = width
            nested.height = height
            return nested
        
        return None
    
    def _generate_candidate_positions(self, width: float, height: float) -> List[Tuple[float, float]]:
        """Generate candidate positions for placement"""
        candidates = []
        
        # Start from origin
        candidates.append((self.margin, self.margin))
        
        # Add positions next to existing shapes
        for nested in self.nested_shapes:
            bounds = nested.get_bounds()
            
            # Right of existing shape
            candidates.append((bounds[2] + self.margin, bounds[1]))
            
            # Top of existing shape
            candidates.append((bounds[0], bounds[3] + self.margin))
            
            # Right-top corner
            candidates.append((bounds[2] + self.margin, bounds[3] + self.margin))
        
        # Remove duplicates and sort
        candidates = list(set(candidates))
        candidates.sort(key=lambda p: (p[1], p[0]))  # Sort by y, then x
        
        return candidates
    
    def _has_collision(self, test_shape: NestedShape) -> bool:
        """Check if test_shape collides with any placed shapes"""
        for nested in self.nested_shapes:
            if test_shape.overlaps(nested, self.margin):
                return True
        return False
    
    def get_utilization(self) -> float:
        """Calculate sheet utilization percentage"""
        if not self.nested_shapes:
            return 0.0
        
        used_area = sum(n.width * n.height for n in self.nested_shapes)
        sheet_area = self.sheet_width * self.sheet_height
        return (used_area / sheet_area * 100) if sheet_area > 0 else 0.0
