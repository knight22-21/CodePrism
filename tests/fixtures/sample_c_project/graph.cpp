#include <string>
#include <vector>
#include <iostream>

namespace prism {

class Node {
public:
    std::string name;
    int value;

    Node(const std::string& name, int value) : name(name), value(value) {}

    virtual ~Node() = default;

    std::string toString() const {
        return name + ":" + std::to_string(value);
    }
};

class GraphNode : public Node {
public:
    std::vector<GraphNode*> neighbors;

    GraphNode(const std::string& name, int value) : Node(name, value) {}

    void addNeighbor(GraphNode* node) {
        neighbors.push_back(node);
    }

    int degree() const {
        if (neighbors.empty()) {
            return 0;
        }
        return static_cast<int>(neighbors.size());
    }
};

GraphNode* create_node(const std::string& name, int value) {
    return new GraphNode(name, value);
}

} // namespace prism
