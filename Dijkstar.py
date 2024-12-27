from flask import Flask, request, jsonify
from pymongo import MongoClient
import json
import heapq
from math import sqrt

app = Flask(__name__)

# เชื่อมต่อ MongoDB
uri = "mongodb+srv://peeradol75:peeradon516@geo-database.3gddu.mongodb.net/test?retryWrites=true&w=majority"
client = MongoClient(uri)
database = client.get_database("test")
collection = database.get_collection("routes")

def calculate_distance(point1, point2):
    return sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)
def find_nearest_point(target_point, graph):
    if not graph:
        return None
    
    nearest_point = None
    min_distance = float('inf')
    
    for point in graph.keys():
        distance = calculate_distance(target_point, point)
        if distance < min_distance:
            min_distance = distance
            nearest_point = point
            
    # ถ้าจุดที่ใกล้ที่สุดห่างเกินไป อาจจะ return None
    # สามารถกำหนด threshold ได้
    DISTANCE_THRESHOLD = 0.001  # ประมาณ 100 เมตร
    if min_distance > DISTANCE_THRESHOLD:
        return None
        
    return nearest_point
def build_graph(routes):
    graph = {}
    for route in routes:
        coordinates = route['geometry']['coordinates']
        for i in range(len(coordinates) - 1):
            # แก้ลำดับให้เป็น (lat, lon)
            start = (coordinates[i][1], coordinates[i][0])  # สลับ lat, lon
            end = (coordinates[i + 1][1], coordinates[i + 1][0])  # สลับ lat, lon
            if start not in graph:
                graph[start] = {}
            if end not in graph:
                graph[end] = {}
            graph[start][end] = 1
            graph[end][start] = 1
    return graph

def dijkstra(graph, start, end):
    queue = [(0, start)]
    distances = {start: 0}
    previous_nodes = {start: None}
    
    while queue:
        current_distance, current_node = heapq.heappop(queue)

        if current_node == end:
            path = []
            while previous_nodes[current_node] is not None:
                path.append(current_node)
                current_node = previous_nodes[current_node]
            path.append(start)
            return path[::-1]

        for neighbor, weight in graph.get(current_node, {}).items():
            distance = current_distance + weight
            if neighbor not in distances or distance < distances[neighbor]:
                distances[neighbor] = distance
                previous_nodes[neighbor] = current_node
                heapq.heappush(queue, (distance, neighbor))

    return None

@app.route('/directions', methods=['GET'])
def directions():
    try:
        start_lat = float(request.args.get('startLat'))
        start_lon = float(request.args.get('startLon'))
        end_lat = float(request.args.get('endLat'))
        end_lon = float(request.args.get('endLon'))

        # เพิ่มการตรวจสอบระยะทางขั้นต่ำ
        MIN_DISTANCE = 0.0001  # ประมาณ 10 เมตร
        start_point = (start_lat, start_lon)
        end_point = (end_lat, end_lon)
        
        if calculate_distance(start_point, end_point) < MIN_DISTANCE:
            return jsonify({
                "error": "Start and end points are too close"
            }), 400

        routes = list(collection.find({}))
        graph = build_graph(routes)

        nearest_start = find_nearest_point(start_point, graph)
        nearest_end = find_nearest_point(end_point, graph)

        if not nearest_start or not nearest_end:
            return jsonify({
                "error": "No nearby road found for start or end point"
            }), 404

        path = dijkstra(graph, nearest_start, nearest_end)
        
        if path:
            return jsonify({"path": path}), 200
        return jsonify({"error": "No path found"}), 404
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == '__main__':
    app.run(debug=True, port=5000)
