"""
FastAPI Server for Nesting Software
"""

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import zipfile
import json
from pathlib import Path
from typing import Optional
import copy
from dxf_reader import DXFReader
from nesting_algorithm import NestingAlgorithm
from dxf_exporter import DXFExporter
from nc_exporter import NCExporter
from pdf_report import generate_all_reports

# Configuration
UPLOAD_FOLDER = Path('uploads')
OUTPUT_FOLDER = Path('outputs')
ALLOWED_EXTENSIONS = {'dxf'}

# Create directories
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

# FastAPI app
app = FastAPI(
    title="Nesting Software API",
    description="API for DXF nesting and optimization",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files in production (built React app)
static_folder = Path("../client/build")
if static_folder.exists():
    # Serve static assets (JS, CSS, images, etc.) from build/static
    static_assets = static_folder / "static"
    if static_assets.exists():
        app.mount("/static", StaticFiles(directory=str(static_assets)), name="static")


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _serialize_holes(holes):
    """Serialize holes for JSON: circle holes as {type, center, radius}, polyline as list of points."""
    if not holes:
        return []
    result = []
    for hole in holes:
        if isinstance(hole, dict) and hole.get("type") == "circle":
            result.append({
                "type": "circle",
                "center": list(hole["center"]) if hole.get("center") else [0, 0],
                "radius": float(hole.get("radius", 0))
            })
        elif isinstance(hole, (list, tuple)):
            result.append([[float(p[0]), float(p[1])] for p in hole])
        else:
            result.append(hole)
    return result


def shape_to_dict(shape):
    """Convert Shape object to dictionary"""
    holes = shape.holes if hasattr(shape, 'holes') else []
    origin = getattr(shape, 'origin', None)
    return {
        "shape_id": shape.shape_id,
        "shape_type": shape.shape_type,
        "points": shape.points,
        "holes": _serialize_holes(holes),
        "width": shape.width,
        "height": shape.height,
        "radius": float(shape.radius) if getattr(shape, 'radius', None) is not None else 0,
        "center": list(shape.center) if shape.center else None,
        "bounding_box": list(shape.bounding_box),
        "area": shape.area,
        "origin": list(origin) if origin else None
    }


def nested_shape_to_dict(nested_shape):
    """Convert NestedShape object to dictionary"""
    return {
        "x": nested_shape.x,
        "y": nested_shape.y,
        "rotation": nested_shape.rotation,
        "width": nested_shape.width,
        "height": nested_shape.height,
        "original_shape": shape_to_dict(nested_shape.original_shape)
    }


@app.get("/")
async def root():
    """Root endpoint - serve index.html in production"""
    if static_folder.exists():
        index_path = static_folder / "index.html"
        if index_path.exists():
            return FileResponse(
                str(index_path),
                media_type="text/html"
            )
    return {"message": "Nesting Software API", "status": "running", "note": "Frontend not built. Run 'npm run build' in client directory."}


@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "message": "Nesting Software API is running"}


@app.post("/api/preview-shapes")
async def preview_shapes(file: UploadFile = File(...)):
    """Preview shapes from uploaded DXF file"""
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")
        
        if not allowed_file(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only .dxf files are allowed"
            )
        
        # Save uploaded file temporarily
        filename = file.filename.replace(' ', '_')
        input_path = UPLOAD_FOLDER / filename
        
        with open(input_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Read DXF file
        reader = DXFReader(str(input_path))
        shapes = reader.read()
        
        # Clean up
        input_path.unlink()
        
        if not shapes:
            raise HTTPException(
                status_code=400,
                detail="No shapes found in DXF file"
            )
        
        # Convert shapes to dictionaries
        shapes_data = [shape_to_dict(shape) for shape in shapes]
        
        return {
            "shapes": shapes_data,
            "count": len(shapes_data)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error previewing shapes: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Error previewing shapes: {str(e)}'
        )


@app.post("/api/process")
async def process_dxf(
    file: UploadFile = File(...),
    sheetWidth: float = Form(2000),
    sheetHeight: float = Form(1000),
    margin: float = Form(5),
    allowRotation: str = Form("true"),
    feedRate: float = Form(1200),
    cutDepth: float = Form(-3),
    selectedIndices: str = Form("[]"),
    shapeQuantities: str = Form("{}"),
    projectName: str = Form(""),
    materialSpec: str = Form(""),
    materialThickness: float = Form(0),
    materialDensity: float = Form(7850),
):
    """Process DXF file and create nested layout"""
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file selected")
        
        if not allowed_file(file.filename):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only .dxf files are allowed"
            )
        
        # Parse boolean
        allow_rotation = allowRotation.lower() == 'true'
        
        # Save uploaded file
        filename = file.filename.replace(' ', '_')  # Simple sanitization
        input_path = UPLOAD_FOLDER / filename
        
        with open(input_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Step 1: Read DXF file
        reader = DXFReader(str(input_path))
        all_shapes = reader.read()
        
        if not all_shapes:
            input_path.unlink()  # Clean up
            raise HTTPException(
                status_code=400,
                detail="No shapes found in DXF file"
            )
        
        # Step 2: Filter shapes based on selection and quantities
        try:
            selected_indices = json.loads(selectedIndices) if selectedIndices else []
        except:
            selected_indices = list(range(len(all_shapes)))  # Select all if invalid

        # Parse per-shape quantities (mapping of index -> quantity)
        try:
            quantities_raw = json.loads(shapeQuantities) if shapeQuantities else {}
        except:
            quantities_raw = {}

        index_quantities = {}
        if isinstance(quantities_raw, dict):
            for key, value in quantities_raw.items():
                try:
                    idx = int(key)
                    qty = int(value)
                except (ValueError, TypeError):
                    continue
                if qty > 0 and 0 <= idx < len(all_shapes):
                    index_quantities[idx] = qty

        # Backwards compatibility: if no quantities provided, fall back to selected indices (qty = 1)
        if not index_quantities:
            for idx in selected_indices:
                if 0 <= idx < len(all_shapes):
                    index_quantities[idx] = index_quantities.get(idx, 0) + 1

        if not index_quantities:
            input_path.unlink()
            raise HTTPException(
                status_code=400,
                detail="No shapes selected"
            )

        # Build shapes list, duplicating shapes according to requested quantity
        shapes = []
        for idx, qty in index_quantities.items():
            base_shape = all_shapes[idx]
            for _ in range(qty):
                shapes.append(copy.deepcopy(base_shape))
        
        # Step 3: Multi-sheet nesting
        remaining_shapes = shapes.copy()
        sheets = []
        sheet_data_list = []  # Store actual NestedShape objects for export
        sheet_number = 1
        total_placed = 0
        
        while remaining_shapes:
            nesting = NestingAlgorithm(
                sheet_width=sheetWidth,
                sheet_height=sheetHeight,
                margin=margin,
                allow_rotation=allow_rotation
            )
            
            nested_shapes, utilization = nesting.nest(remaining_shapes)
            
            if not nested_shapes:
                # No more shapes can be placed
                break
            
            # Calculate optimized sheet height (based on maximum Y coordinate of placed shapes)
            max_y = 0.0
            for ns in nested_shapes:
                # Get the top edge of the shape (y + height)
                top_edge = ns.y + ns.height
                if top_edge > max_y:
                    max_y = top_edge
            
            # Add margin to get optimized height
            optimized_height = max_y + margin if max_y > 0 else sheetHeight
            
            # Track which shapes were placed (by object identity, not just ID)
            placed_shapes = {ns.original_shape for ns in nested_shapes}

            # Recalculate utilization with optimized height for accuracy
            used_area = sum(n.width * n.height for n in nested_shapes)
            optimized_sheet_area = sheetWidth * optimized_height
            utilization = (used_area / optimized_sheet_area * 100) if optimized_sheet_area > 0 else 0
            
            # Store sheet data with actual objects for export (including optimized height)
            sheet_data_list.append({
                'nested_shapes': nested_shapes,
                'sheet_number': sheet_number,
                'optimized_height': optimized_height
            })
            
            # Remove placed shapes from remaining
            remaining_shapes = [s for s in remaining_shapes if s not in placed_shapes]
            
            sheets.append({
                'sheetNumber': sheet_number,
                'nestedShapes': [nested_shape_to_dict(ns) for ns in nested_shapes],
                'sheetWidth': sheetWidth,
                'sheetHeight': optimized_height,  # Use optimized height
                'utilization': round(utilization, 2),
                'shapesCount': len(nested_shapes)
            })
            
            total_placed += len(nested_shapes)
            sheet_number += 1
        
        if not sheets:
            input_path.unlink()
            raise HTTPException(
                status_code=400,
                detail="Could not place any shapes on the sheet"
            )
        
        # Step 4: Export all sheets to DXF and NC
        output_files = []
        
        for sheet_data_obj in sheet_data_list:
            sheet_num = sheet_data_obj['sheet_number']
            nested_shapes_objs = sheet_data_obj['nested_shapes']
            optimized_height = sheet_data_obj.get('optimized_height', sheetHeight)
            
            # Export DXF for this sheet (use optimized height) - without sheet boundary
            output_dxf = OUTPUT_FOLDER / f'nested_layout_sheet_{sheet_num}.dxf'
            dxf_exporter = DXFExporter(str(output_dxf), sheetWidth, optimized_height)
            dxf_exporter.add_nested_shapes(nested_shapes_objs)
            dxf_exporter.save()
            output_files.append((output_dxf, f'nested_layout_sheet_{sheet_num}.dxf'))
            
            # Export NC for this sheet
            output_nc = OUTPUT_FOLDER / f'nested_program_sheet_{sheet_num}.nc'
            nc_exporter = NCExporter(
                str(output_nc),
                feed_rate=feedRate,
                cut_depth=cutDepth
            )
            nc_exporter.header(f"NESTED_LAYOUT_SHEET_{sheet_num}")
            nc_exporter.spindle_on(18000)
            nc_exporter.add_nested_shapes(nested_shapes_objs)
            nc_exporter.spindle_off()
            nc_exporter.footer()
            nc_exporter.save()
            output_files.append((output_nc, f'nested_program_sheet_{sheet_num}.nc'))
        
        # Generate PDF reports (Nest Overview + Utilisation)
        project_name = projectName.strip() or file.filename.replace(".dxf", "").replace(".DXF", "")
        try:
            pdf_files = generate_all_reports(
                OUTPUT_FOLDER,
                project_name=project_name,
                sheets=sheets,
                material_spec=materialSpec.strip() or "",
                material_thickness_mm=float(materialThickness) if materialThickness else 0,
                material_density=float(materialDensity) if materialDensity else 7850,
            )
            output_files.extend(pdf_files)
        except Exception as e:
            print(f"PDF report generation failed: {e}")

        # Create ZIP file with all outputs
        zip_path = OUTPUT_FOLDER / 'nested_results.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arc_name in output_files:
                zipf.write(file_path, arc_name)
        
        # Store results
        results = {
            'totalShapes': len(shapes),
            'placedShapes': total_placed,
            'unplacedShapes': len(remaining_shapes),
            'totalSheets': len(sheets),
            'utilization': round(sum(s['utilization'] for s in sheets) / len(sheets), 2) if sheets else 0
        }
        
        results_path = OUTPUT_FOLDER / 'results.json'
        with open(results_path, 'w') as f:
            json.dump(results, f)
        
        # Clean up input file
        input_path.unlink()
        
        # Return JSON with multi-sheet data
        return JSONResponse({
            "success": True,
            "results": results,
            "sheets": sheets,
            "totalSheets": len(sheets),
            "totalShapes": len(shapes),
            "placedShapes": total_placed,
            "unplacedShapes": len(remaining_shapes),
            "shapes": [shape_to_dict(shape) for shape in shapes],
            "zipUrl": "/api/download-results"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f'Processing error: {str(e)}'
        )


@app.get("/api/results")
async def get_results():
    """Get processing results"""
    try:
        results_path = OUTPUT_FOLDER / 'results.json'
        if results_path.exists():
            with open(results_path, 'r') as f:
                results = json.load(f)
            return results
        raise HTTPException(status_code=404, detail="No results available")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download-results")
async def download_results():
    """Download the generated ZIP file"""
    zip_path = OUTPUT_FOLDER / 'nested_results.zip'
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Results file not found")
    
    return FileResponse(
        path=str(zip_path),
        media_type='application/zip',
        filename='nested_results.zip'
    )


# Catch-all route for React Router (serve index.html for all non-API routes)
@app.get("/{full_path:path}")
async def serve_react_app(full_path: str):
    """Serve React app for all non-API routes"""
    # Don't interfere with API routes
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # Don't interfere with static assets
    if full_path.startswith("static/") or full_path.startswith("assets/"):
        raise HTTPException(status_code=404, detail="Static file not found")
    
    # Serve index.html for all other routes (React Router)
    if static_folder.exists():
        index_path = static_folder / "index.html"
        if index_path.exists():
            return FileResponse(
                str(index_path),
                media_type="text/html"
            )
    
    return {"message": "Frontend not built. Run 'npm run build' in client directory."}


if __name__ == "__main__":
    import uvicorn
    print("Starting Nesting Software API Server...")
    print("API available at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
