#include <stdio.h>
#include <stdlib.h>
#include <math.h>

typedef struct {
    int x;
    int y;
} Point;

struct Rectangle {
    Point top_left;
    Point bottom_right;
};

enum Color {
    RED,
    GREEN,
    BLUE
};

int compute_area(struct Rectangle *rect) {
    int width = rect->bottom_right.x - rect->top_left.x;
    int height = rect->bottom_right.y - rect->top_left.y;
    return width * height;
}

double compute_distance(Point a, Point b) {
    int dx = b.x - a.x;
    int dy = b.y - a.y;
    return sqrt((double)(dx * dx + dy * dy));
}

void print_point(Point p) {
    printf("(%d, %d)\n", p.x, p.y);
}

int main(int argc, char *argv[]) {
    Point origin = {0, 0};
    Point p = {3, 4};
    print_point(origin);
    double d = compute_distance(origin, p);
    printf("distance: %f\n", d);
    return 0;
}
