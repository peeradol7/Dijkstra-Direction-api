from flask import Flask, json, request, jsonify
import networkx as nx
from math import radians, sin, cos, sqrt, atan2
from pymongo import MongoClient
import logging

# ตั้งค่าการ Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# MongoDB Client
client = MongoClient("mongodb+srv://peeradol75:peeradon516@geo-database.3gddu.mongodb.net/test?retryWrites=true&w=majority")
db = client['geojson_db']
collection = db['map_data']

def save_geojson_file_to_mongodb(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as geojson_file:
            geojson_data = json.load(geojson_file)
            collection.insert_one(geojson_data)
            print("GeoJSON data saved to MongoDB successfully.")
    except Exception as e:
        print(f"Error while saving GeoJSON to MongoDB: {e}")

# คำนวณระยะทางระหว่างพิกัด
def calculate_distance(coord1, coord2):
    R = 6371  # Radius of Earth in km
    lat1, lon1 = radians(coord1[1]), radians(coord1[0])
    lat2, lon2 = radians(coord2[1]), radians(coord2[0])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = R * c
    return distance

# สร้างกราฟจาก GeoJSON
def build_graph_from_geojson(geojson_data):
    graph = nx.Graph()

    for feature_idx, feature in enumerate(geojson_data["features"]):
        if feature["geometry"]["type"] == "LineString":
            coords = feature["geometry"]["coordinates"]

            for i in range(len(coords) - 1):
                node1 = tuple(coords[i])
                node2 = tuple(coords[i + 1])
                distance = calculate_distance(node1, node2)
                graph.add_edge(node1, node2,
                               weight=distance,
                               linestring_id=feature_idx,
                               is_original_path=True)

    return graph

# ดึงข้อมูล GeoJSON จาก MongoDB
def fetch_geojson_from_mongodb():
    try:
        cursor = collection.find({})
        geojson_data = {
            "type": "FeatureCollection",
            "features": []
        }

        for doc in cursor:
            geojson_data["features"].extend(doc["features"])

        return geojson_data

    except Exception as e:
        logger.error(f"Error fetching GeoJSON from MongoDB: {str(e)}", exc_info=True)
        raise e

# ค้นหา Node ที่ใกล้ที่สุด
def find_nearest_node(point, graph, max_distance=0.6):
    nearest_node = None
    min_distance = float('inf')

    for node in graph.nodes():
        distance = calculate_distance(point, node)
        if distance < min_distance and distance <= max_distance:
            min_distance = distance
            nearest_node = node

    return nearest_node, min_distance

# ตรวจสอบว่าพิกัดตรงกันหรือไม่
def coordinates_are_equal(coord1, coord2):
    return round(coord1[0], 6) == round(coord2[0], 6) and round(coord1[1], 6) == round(coord2[1], 6)
def connect_paths(graph, start_node, end_node, max_connection_distance=0.1):
    """
    พยายามเชื่อมต่อระหว่าง path ที่ขาดหายไป
    
    Args:
        graph: NetworkX graph object
        start_node: จุดเริ่มต้นที่ต้องการเชื่อม
        end_node: จุดปลายทางที่ต้องการเชื่อม
        max_connection_distance: ระยะทางสูงสุดที่ยอมให้เชื่อมต่อระหว่าง path (หน่วยเป็น km)
    
    Returns:
        path: เส้นทางที่เชื่อมต่อได้ หรือ None ถ้าไม่สามารถเชื่อมต่อได้
    """
    # หาจุดที่ใกล้ที่สุดในกราฟสำหรับทั้งจุดเริ่มต้นและจุดสิ้นสุด
    possible_starts = []
    possible_ends = []
    
    for node in graph.nodes():
        start_dist = calculate_distance(start_node, node)
        end_dist = calculate_distance(end_node, node)
        
        if start_dist <= max_connection_distance:
            possible_starts.append((node, start_dist))
        if end_dist <= max_connection_distance:
            possible_ends.append((node, end_dist))
    
    # เรียงลำดับตามระยะทาง
    possible_starts.sort(key=lambda x: x[1])
    possible_ends.sort(key=lambda x: x[1])
    
    # ลองหาเส้นทางจากจุดที่เป็นไปได้ทั้งหมด
    shortest_path = None
    min_total_distance = float('inf')
    
    for start, start_dist in possible_starts:
        for end, end_dist in possible_ends:
            try:
                path = nx.shortest_path(graph, start, end, weight='weight')
                path_distance = sum(
                    calculate_distance(path[i], path[i + 1])
                    for i in range(len(path) - 1)
                )
                total_distance = path_distance + start_dist + end_dist
                
                if total_distance < min_total_distance:
                    min_total_distance = total_distance
                    shortest_path = path
            except nx.NetworkXNoPath:
                continue
    
    return shortest_path, min_total_distance if shortest_path else (None, None)

@app.route('/find-path', methods=['POST'])
def find_path():
    try:
        data = request.get_json()
        start_point = tuple(data['start'])
        waypoints = [tuple(wp) for wp in data.get('waypoints', [])]
        end_point = tuple(data['end'])
        
        geojson_data = fetch_geojson_from_mongodb()
        graph = build_graph_from_geojson(geojson_data)
        
        all_points = [start_point] + waypoints + [end_point]
        full_path = []
        total_distance = 0
        
        for i in range(len(all_points) - 1):
            current_start = all_points[i]
            current_end = all_points[i + 1]
            
            # หาจุดที่ใกล้ที่สุดในกราฟ
            start_node, start_distance = find_nearest_node(current_start, graph)
            end_node, end_distance = find_nearest_node(current_end, graph)
            
            if start_node is None or end_node is None:
                # ลองเชื่อมต่อระหว่าง path
                connected_path, connected_distance = connect_paths(
                    graph, current_start, current_end,max_connection_distance=0.4
                )
                start_node, start_distance = find_nearest_node(current_start, graph)
                end_node, end_distance = find_nearest_node(current_end, graph)
                logger.info(f"Distance to nearest start node: {start_distance}")
                logger.info(f"Distance to nearest end node: {end_distance}")
                if connected_path is None:
                    return jsonify({
                        "error": f"Cannot find path between {current_start} and {current_end}, "
                                f"even after attempting to connect different paths"
                    }), 400
                
                # เพิ่ม connected path เข้าไปใน full path
                for coord in connected_path:
                    if not full_path or not coordinates_are_equal(tuple(full_path[-1]), coord):
                        full_path.append(list(coord))
                total_distance += connected_distance
            else:
                # คำนวณเส้นทางปกติ
                sub_path = nx.shortest_path(graph, start_node, end_node, weight='weight')
                for coord in sub_path:
                    if not full_path or not coordinates_are_equal(tuple(full_path[-1]), coord):
                        full_path.append(list(coord))
                
                segment_distance = sum(
                    calculate_distance(sub_path[i], sub_path[i + 1])
                    for i in range(len(sub_path) - 1)
                )
                total_distance += segment_distance + start_distance + end_distance
        
        return jsonify({
            "path": full_path,
            "total_distance": total_distance
        })
        
    except Exception as e:
        logger.error(f"Error in find_path: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    save_geojson_file_to_mongodb('./map.geojson')
    app.run(host="0.0.0.0", port=5000)
    app.run(debug=True)
