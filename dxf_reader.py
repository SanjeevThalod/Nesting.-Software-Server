"""
DXF Reader - Extracts shapes from DXF files
Uses hybrid approach: direct entities + EdgeSmith/EdgeMiner for composite shapes
"""

import ezdxf
from ezdxf.entities import LWPolyline, Circle, Polyline, Point
from typing import List, Tuple, Optional, Set, Union
import math

# Gap tolerance for connecting edges (mm) - handles real-world DXF inaccuracies
GAP_TOL = 0.1

# A hole is either a polyline (list of points) or a circle (dict with type, center, radius)
HoleType = Union[List[Tuple[float, float]], dict]

# EdgeSmith and EdgeMiner (ezdxf 1.4+)
try:
    from ezdxf import edgesmith, edgeminer
    HAS_EDGEMINER = True
except ImportError:
    HAS_EDGEMINER = False


class Shape:
    """Represents a shape extracted from DXF"""
    def __init__(self, shape_id: str = ""):
        self.shape_id = shape_id
        self.points: List[Tuple[float, float]] = []
        self.holes: List[HoleType] = []  # Holes: list of points (polyline) or {"type":"circle","center":(x,y),"radius":r}
        self.shape_type: str = "polyline"  # "rectangle", "circle", "polyline"
        self.width: float = 0.0
        self.height: float = 0.0
        self.radius: float = 0.0
        self.center: Tuple[float, float] = (0.0, 0.0)
        self.bounding_box: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # min_x, min_y, max_x, max_y
        self.area: float = 0.0
        self.origin: Optional[Tuple[float, float]] = None

    def calculate_bounding_box(self):
        """Calculate bounding box of the shape"""
        if not self.points:
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        self.bounding_box = (min(xs), min(ys), max(xs), max(ys))
        self.width = max(xs) - min(xs)
        self.height = max(ys) - min(ys)

    def get_bounds(self) -> Tuple[float, float, float, float]:
        """Get bounding box (min_x, min_y, max_x, max_y)"""
        return self.bounding_box


class DXFReader:
    """Reads and extracts shapes from DXF files using hybrid boundary detection"""

    DIMENSION_LAYERS = {'dimensions', 'dim', 'dimension', 'dims', 'annotations', 'annotation', 'text'}

    def __init__(self, filename: str, gap_tol: float = GAP_TOL):
        self.filename = filename
        self.doc = None
        self.shapes: List[Shape] = []
        self.gap_tol = gap_tol

    def read(self) -> List[Shape]:
        """Read DXF file and extract complete shapes"""
        try:
            self.doc = ezdxf.readfile(self.filename)
        except IOError:
            print(f"Error: File '{self.filename}' not found or invalid DXF file")
            return []
        except ezdxf.DXFStructureError:
            print(f"Error: Invalid DXF structure in '{self.filename}'")
            return []

        msp = self.doc.modelspace()

        # Step 1: Extract closed loops from direct entities (Circle, closed Polyline, Point)
        closed_loops = self._extract_closed_loops(msp)

        # Step 2: Extract composite shapes from edges (LINE, ARC, ELLIPSE, SPLINE, open polylines)
        if HAS_EDGEMINER:
            edgeminer_loops = self._extract_loops_from_edges(msp)
            closed_loops.extend(edgeminer_loops)
        else:
            print("  Note: ezdxf EdgeSmith/EdgeMiner not available (need ezdxf>=1.4). Using basic extraction only.")

        # Step 3: Filter dimension lines and tiny artifacts
        closed_loops = self._filter_dimensions_and_artifacts(closed_loops)

        # Step 4: Detect outer boundaries and holes
        self.shapes = self._detect_boundaries_and_holes(closed_loops)

        print(f"Extracted {len(self.shapes)} complete shapes from DXF file")
        return self.shapes

    def _is_dimension_layer(self, entity) -> bool:
        """Check if entity is on a dimension/annotation layer"""
        try:
            if hasattr(entity.dxf, 'layer'):
                layer = entity.dxf.layer.lower()
                return any(dim in layer for dim in self.DIMENSION_LAYERS)
        except Exception:
            pass
        return False

    def _extract_closed_loops(self, msp) -> List[Shape]:
        """Extract closed loops from direct entities (Circle, closed Polyline, Point)"""
        loops = []
        shape_counter = 1

        for entity in msp:
            if self._is_dimension_layer(entity):
                continue

            shape = None
            layer_name = getattr(entity.dxf, 'layer', '') or ''

            if isinstance(entity, LWPolyline) and entity.closed:
                shape = self._extract_lwpolyline(entity, f"Shape_{shape_counter}")
                shape_counter += 1
            elif isinstance(entity, Polyline) and entity.is_closed:
                shape = self._extract_polyline(entity, f"Shape_{shape_counter}")
                shape_counter += 1
            elif isinstance(entity, Circle):
                shape = self._extract_circle(entity, f"Shape_{shape_counter}")
                shape_counter += 1
            elif isinstance(entity, Point):
                shape = self._extract_point(entity, f"Shape_{shape_counter}")
                shape_counter += 1

            if shape:
                shape.calculate_bounding_box()
                loops.append(shape)
                print(f"  Extracted {entity.dxf.dxftype} on layer '{layer_name}' as loop.")

        return loops

    def _extract_loops_from_edges(self, msp) -> List[Shape]:
        """Extract closed loops from composite shapes (LINE, ARC, ELLIPSE, SPLINE, open polylines) using EdgeSmith + EdgeMiner"""
        loops = []
        shape_counter_start = 1000  # Avoid ID collision with direct entities

        # Collect entities that can form edges (exclude dimension layers)
        entities = [e for e in msp if not self._is_dimension_layer(e)]

        try:
            edge_list = list(edgesmith.edges_from_entities_2d(entities, gap_tol=self.gap_tol))
        except Exception as e:
            print(f"  EdgeSmith edge creation failed: {e}")
            return []

        if not edge_list:
            return []

        try:
            deposit = edgeminer.Deposit(edge_list, gap_tol=self.gap_tol)
        except Exception as e:
            print(f"  EdgeMiner Deposit failed: {e}")
            return []

        try:
            found_loops = edgeminer.find_all_loops(deposit, timeout=30.0)
        except Exception as e:
            # TimeoutError has .solutions with partial results
            found_loops = getattr(e, 'solutions', []) or []
            if found_loops:
                print(f"  EdgeMiner find_all_loops timed out. Using {len(found_loops)} loops found so far.")
            else:
                print(f"  EdgeMiner find_all_loops failed: {e}")
                return []

        for idx, loop_edges in enumerate(found_loops):
            if not loop_edges or len(loop_edges) < 2:
                continue

            try:
                lwp = edgesmith.lwpolyline_from_chain(loop_edges, max_sagitta=0.01)
            except Exception:
                continue

            points = []
            try:
                with lwp.points() as pts:
                    for pt in pts:
                        points.append((float(pt[0]), float(pt[1])))
            except Exception:
                continue

            if len(points) < 3:
                continue

            shape = Shape(f"Shape_{shape_counter_start + idx}")
            shape.shape_type = "polyline"
            shape.points = points
            shape.area = self._calculate_polygon_area(points)
            shape.calculate_bounding_box()

            # Filter tiny loops (likely artifacts)
            if shape.width >= 1.0 and shape.height >= 1.0:
                loops.append(shape)
                print(f"  Extracted composite loop (EdgeMiner) as {shape.shape_id}.")

        return loops

    def _filter_dimensions_and_artifacts(self, loops: List[Shape]) -> List[Shape]:
        """Filter out dimension lines and tiny artifacts"""
        print(f"Extracted {len(loops)} initial loops.")
        filtered = [l for l in loops if l.width >= 1.0 and l.height >= 1.0]
        for l in loops:
            if l.width < 1.0 or l.height < 1.0:
                print(f"  Filtering out tiny loop {l.shape_id}: {l.width}x{l.height}")
        print(f"Filtered down to {len(filtered)} loops.")
        return filtered

    def _detect_boundaries_and_holes(self, loops: List[Shape]) -> List[Shape]:
        """Detect outer boundaries and holes (holes are inside boundaries)"""
        if not loops:
            return []

        loops.sort(key=lambda s: s.area, reverse=True)
        shapes = []
        used = set()

        for i, outer_loop in enumerate(loops):
            if i in used:
                continue

            print(f"Processing outer loop candidate: {outer_loop.shape_id} ({outer_loop.width}x{outer_loop.height})")

            holes = []
            for j, potential_hole in enumerate(loops):
                if j in used or i == j:
                    continue
                if self._is_inside(potential_hole, outer_loop):
                    if potential_hole.shape_type == "circle":
                        holes.append({"type": "circle", "center": potential_hole.center, "radius": potential_hole.radius})
                    else:
                        holes.append(potential_hole.points)
                    used.add(j)
                    print(f"    Detected hole {potential_hole.shape_id} inside {outer_loop.shape_id}")

            complete_shape = Shape(f"Shape_{len(shapes)+1}")
            complete_shape.points = outer_loop.points
            complete_shape.holes = holes
            complete_shape.shape_type = outer_loop.shape_type
            complete_shape.bounding_box = outer_loop.bounding_box
            complete_shape.width = outer_loop.width
            complete_shape.height = outer_loop.height
            complete_shape.area = outer_loop.area - sum(self._hole_area(hole) for hole in holes)
            complete_shape.origin = getattr(outer_loop, 'origin', None) or (outer_loop.bounding_box[0], outer_loop.bounding_box[1])

            shapes.append(complete_shape)
            used.add(i)
            print(f"Finalized shape {complete_shape.shape_id} with {len(holes)} holes.")

        print(f"Detected {len(shapes)} final shapes.")
        return shapes

    def _is_inside(self, inner_shape: Shape, outer_shape: Shape) -> bool:
        """Check if inner_shape is completely inside outer_shape"""
        inner_bb = inner_shape.bounding_box
        outer_bb = outer_shape.bounding_box
        if not (outer_bb[0] <= inner_bb[0] and outer_bb[1] <= inner_bb[1] and
                outer_bb[2] >= inner_bb[2] and outer_bb[3] >= inner_bb[3]):
            return False
        inner_center = ((inner_bb[0] + inner_bb[2]) / 2, (inner_bb[1] + inner_bb[3]) / 2)
        return self._point_in_polygon(inner_center, outer_shape.points)

    def _point_in_polygon(self, point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
        """Ray casting algorithm to check if point is inside polygon"""
        if len(polygon) < 3:
            return False
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    def _extract_lwpolyline(self, entity: LWPolyline, shape_id: str) -> Optional[Shape]:
        """Extract points from LWPolyline"""
        shape = Shape(shape_id)
        shape.shape_type = "polyline"

        points = []
        with entity.points() as e:
            for point in e:
                points.append((point[0], point[1]))

        if len(points) == 4 or (len(points) == 5 and points[0] == points[-1]):
            if len(points) == 5:
                points = points[:4]
            if self._is_rectangle(points):
                shape.shape_type = "rectangle"
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                shape.width = max(xs) - min(xs)
                shape.height = max(ys) - min(ys)
                min_x, min_y = min(xs), min(ys)
                shape.points = [(x - min_x, y - min_y) for x, y in points]
                shape.origin = (min_x, min_y)
            else:
                shape.points = points
        else:
            shape.points = points

        shape.area = self._calculate_polygon_area(shape.points)
        return shape

    def _extract_polyline(self, entity: Polyline, shape_id: str) -> Optional[Shape]:
        """Extract points from Polyline"""
        shape = Shape(shape_id)
        shape.shape_type = "polyline"
        points = []
        for vertex in entity.vertices:
            if vertex.dxf.location:
                points.append((vertex.dxf.location.x, vertex.dxf.location.y))
        shape.points = points
        shape.area = self._calculate_polygon_area(points)
        return shape

    def _extract_circle(self, entity: Circle, shape_id: str) -> Optional[Shape]:
        """Extract circle"""
        shape = Shape(shape_id)
        shape.shape_type = "circle"
        shape.center = (entity.dxf.center.x, entity.dxf.center.y)
        shape.radius = entity.dxf.radius
        shape.width = shape.height = shape.radius * 2
        shape.area = math.pi * shape.radius ** 2
        cx, cy = shape.center
        r = shape.radius
        shape.points = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
        shape.bounding_box = (cx - r, cy - r, cx + r, cy + r)
        return shape

    def _is_rectangle(self, points: List[Tuple[float, float]]) -> bool:
        """Check if points form a rectangle"""
        if len(points) != 4:
            return False
        tolerance = 0.01
        for i in range(4):
            p1, p2, p3 = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
            v1 = (p2[0] - p1[0], p2[1] - p1[1])
            v2 = (p3[0] - p2[0], p3[1] - p2[1])
            dot = v1[0] * v2[0] + v1[1] * v2[1]
            len1 = math.sqrt(v1[0]**2 + v1[1]**2)
            len2 = math.sqrt(v2[0]**2 + v2[1]**2)
            if len1 < tolerance or len2 < tolerance:
                continue
            cos_angle = dot / (len1 * len2)
            angle = math.acos(max(-1, min(1, cos_angle)))
            if abs(angle - math.pi/2) > tolerance:
                return False
        return True

    def _hole_area(self, hole: HoleType) -> float:
        """Return area of a hole (polyline or circle)."""
        if isinstance(hole, dict) and hole.get("type") == "circle":
            return math.pi * hole.get("radius", 0) ** 2
        if isinstance(hole, (list, tuple)) and len(hole) >= 3:
            return self._calculate_polygon_area(hole)
        return 0.0

    def _calculate_polygon_area(self, points: List[Tuple[float, float]]) -> float:
        """Calculate polygon area using shoelace formula"""
        if len(points) < 3:
            return 0.0
        area = 0.0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        return abs(area) / 2.0

    def _extract_point(self, entity: Point, shape_id: str) -> Optional[Shape]:
        """Extract a POINT entity as a small shape"""
        shape = Shape(shape_id)
        shape.shape_type = "point"
        x, y, _ = entity.dxf.location
        point_size = 0.1
        shape.points = [
            (x - point_size/2, y - point_size/2),
            (x + point_size/2, y - point_size/2),
            (x + point_size/2, y + point_size/2),
            (x - point_size/2, y + point_size/2)
        ]
        shape.center = (x, y)
        shape.width = point_size
        shape.height = point_size
        shape.area = point_size * point_size
        shape.calculate_bounding_box()
        return shape
