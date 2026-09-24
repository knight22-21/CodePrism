use std::collections::HashMap;

const MAX_RETRIES: u32 = 3;

type RequestId = u64;

pub struct Server {
    host: String,
    port: u16,
    handlers: HashMap<String, u32>,
}

pub enum Status {
    Ok,
    NotFound,
    Error(String),
}

pub trait Handler {
    fn handle(&self, path: &str) -> Status;
    fn name(&self) -> &str;
}

impl Server {
    pub fn new(host: &str, port: u16) -> Self {
        Server {
            host: host.to_string(),
            port,
            handlers: HashMap::new(),
        }
    }

    pub fn start(&self) {
        println!("Starting server on {}:{}", self.host, self.port);
        self.listen();
    }

    fn listen(&self) {
        for _ in 0..MAX_RETRIES {
            log_request(0);
        }
    }
}

pub fn log_request(id: RequestId) {
    println!("Request id: {}", id);
}

fn main() {
    let server = Server::new("localhost", 8080);
    server.start();
}
