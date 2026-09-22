package main

import "fmt"

// Server handles HTTP requests.
type Server struct {
	host string
	port int
}

// NewServer creates a Server with the given host and port.
func NewServer(host string, port int) *Server {
	return &Server{host: host, port: port}
}

// Start starts the server.
func (s *Server) Start() error {
	addr := fmt.Sprintf("%s:%d", s.host, s.port)
	fmt.Println("listening on", addr)
	return nil
}

// Handler is a function that handles a request.
type Handler func(req string) string

// Route pairs a path with a handler.
type Route struct {
	Path    string
	Handler Handler
}

func defaultHandler(req string) string {
	return "ok: " + req
}

func main() {
	srv := NewServer("localhost", 8080)
	if err := srv.Start(); err != nil {
		fmt.Println("error:", err)
	}
}
