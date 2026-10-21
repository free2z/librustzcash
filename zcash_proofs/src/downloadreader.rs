//! [`io::Read`] implementations for [`minreq`].

use std::io;

/// A wrapper that implements [`io::Read`] on a [`minreq::ResponseLazy`].
pub enum ResponseLazyReader {
    Request(minreq::Request),
    Response(minreq::ResponseLazy),
    Complete(Result<(), String>),
}

impl From<minreq::Request> for ResponseLazyReader {
    fn from(request: minreq::Request) -> ResponseLazyReader {
        ResponseLazyReader::Request(request)
    }
}

impl From<minreq::ResponseLazy> for ResponseLazyReader {
    fn from(response: minreq::ResponseLazy) -> ResponseLazyReader {
        ResponseLazyReader::Response(response)
    }
}

impl io::Read for ResponseLazyReader {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        use ResponseLazyReader::{Complete, Request, Response};

        // A zero-sized read is not response EOF and must not dispatch the request.
        if buf.is_empty() {
            return Ok(0);
        }

        loop {
            match self {
                // Launch a lazy response for this request
                Request(request) => match request.clone().send_lazy() {
                    Ok(response) => *self = Response(response),
                    Err(error) => {
                        let error = Err(format!("download request failed: {error:?}"));

                        *self = Complete(error);
                    }
                },

                // Read from the response
                Response(response) => match io::Read::read(response, buf) {
                    Ok(0) => {
                        *self = Complete(Ok(()));
                        return Ok(0);
                    }
                    Ok(read) => return Ok(read),
                    Err(error) => {
                        let error = format!("download response failed: {error:?}");

                        *self = Complete(Err(error.clone()));
                        return Err(io::Error::other(error));
                    }
                },

                Complete(result) => {
                    return match result {
                        // Return a zero-byte read for download success and EOF.
                        Ok(()) => Ok(0),
                        // Keep returning the download error,
                        Err(error) => Err(io::Error::other(error.clone())),
                    };
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::{
        io::{ErrorKind, Read, Write},
        net::{Shutdown, TcpListener},
        sync::mpsc::{self, TryRecvError},
        thread,
        time::{Duration, Instant},
    };

    use super::ResponseLazyReader;

    const LOOPBACK_EPHEMERAL: &str = "127.0.0.1:0";
    const REQUEST_BUFFER_BYTES: usize = 4096;
    const ACCEPT_TIMEOUT: Duration = Duration::from_secs(2);
    const ACCEPT_RETRY_DELAY: Duration = Duration::from_millis(5);
    const TLS_CLIENT_HELLO_PREFIX: &[u8] = &[0x16, 0x03];
    const RESPONSE_BODY: &[u8] = b"parameter bytes";
    const HTTP_OK_RESPONSE: &[u8] =
        b"HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\nparameter bytes";
    const HTTP_MALFORMED_CHUNK_RESPONSE: &[u8] = b"HTTP/1.1 200 OK\r\n\
         Transfer-Encoding: chunked\r\nConnection: close\r\n\r\nnot-hex\r\n";

    fn local_server(
        response: &'static [u8],
    ) -> (String, mpsc::Receiver<Vec<u8>>, thread::JoinHandle<()>) {
        let listener = TcpListener::bind(LOOPBACK_EPHEMERAL).expect("bind loopback server");
        let address = listener.local_addr().expect("read loopback address");
        let (request_sender, request_receiver) = mpsc::channel();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept loopback request");
            let mut request = [0; REQUEST_BUFFER_BYTES];
            let read = stream.read(&mut request).expect("read HTTP request");
            request_sender
                .send(request[..read].to_vec())
                .expect("report HTTP request");
            stream.write_all(response).expect("write HTTP response");
        });

        (
            format!("http://{address}/parameters"),
            request_receiver,
            server,
        )
    }

    #[test]
    fn request_is_dispatched_lazily_and_response_reaches_reader() {
        let (url, request_receiver, server) = local_server(HTTP_OK_RESPONSE);
        let mut reader = ResponseLazyReader::from(minreq::get(url));

        assert_eq!(request_receiver.try_recv(), Err(TryRecvError::Empty));

        let mut body = Vec::new();
        reader.read_to_end(&mut body).expect("read response body");
        assert_eq!(body, RESPONSE_BODY);
        assert!(
            request_receiver
                .recv_timeout(ACCEPT_TIMEOUT)
                .expect("request must reach the server")
                .starts_with(b"GET /parameters HTTP/1.1\r\n")
        );
        server.join().expect("join loopback server");
    }

    #[test]
    fn empty_read_does_not_dispatch_or_complete_request() {
        let (url, request_receiver, server) = local_server(HTTP_OK_RESPONSE);
        let mut reader = ResponseLazyReader::from(minreq::get(url));

        assert_eq!(reader.read(&mut []).expect("empty read"), 0);
        assert_eq!(request_receiver.try_recv(), Err(TryRecvError::Empty));

        let mut body = Vec::new();
        reader.read_to_end(&mut body).expect("read response body");
        assert_eq!(body, RESPONSE_BODY);
        server.join().expect("join loopback server");
    }

    #[test]
    fn completed_response_keeps_returning_eof() {
        let (url, _request_receiver, server) = local_server(HTTP_OK_RESPONSE);
        let mut reader = ResponseLazyReader::from(minreq::get(url));
        let mut body = Vec::new();
        reader.read_to_end(&mut body).expect("read response body");
        assert_eq!(body, RESPONSE_BODY);

        let mut byte = [0];
        assert_eq!(reader.read(&mut byte).expect("first EOF read"), 0);
        assert_eq!(reader.read(&mut byte).expect("second EOF read"), 0);
        server.join().expect("join loopback server");
    }

    #[test]
    fn malformed_response_error_is_propagated_and_retained() {
        let (url, _request_receiver, server) = local_server(HTTP_MALFORMED_CHUNK_RESPONSE);
        let mut reader = ResponseLazyReader::from(minreq::get(url));
        let mut body = Vec::new();

        let first = reader
            .read_to_end(&mut body)
            .expect_err("malformed chunk must fail");
        assert_eq!(first.kind(), ErrorKind::Other);
        assert!(first.to_string().contains("download response failed"));

        let mut byte = [0];
        let retained = reader
            .read(&mut byte)
            .expect_err("response error must remain sticky");
        assert_eq!(retained.kind(), ErrorKind::Other);
        assert_eq!(retained.to_string(), first.to_string());
        server.join().expect("join loopback server");
    }

    #[test]
    fn https_feature_attempts_a_tls_connection() {
        let listener = TcpListener::bind(LOOPBACK_EPHEMERAL).expect("bind TLS probe server");
        listener
            .set_nonblocking(true)
            .expect("make TLS probe nonblocking");
        let address = listener.local_addr().expect("read TLS probe address");
        let (client_hello_sender, client_hello_receiver) = mpsc::channel();
        let server = thread::spawn(move || {
            let deadline = Instant::now() + ACCEPT_TIMEOUT;
            loop {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let mut request = [0; REQUEST_BUFFER_BYTES];
                        let read = stream.read(&mut request).expect("read TLS client hello");
                        client_hello_sender
                            .send(Some(request[..read].to_vec()))
                            .expect("report TLS connection");
                        stream.shutdown(Shutdown::Both).expect("close TLS probe");
                        return;
                    }
                    Err(error) if error.kind() == ErrorKind::WouldBlock => {
                        if Instant::now() >= deadline {
                            client_hello_sender
                                .send(None)
                                .expect("report absent TLS connection");
                            return;
                        }
                        thread::sleep(ACCEPT_RETRY_DELAY);
                    }
                    Err(error) => panic!("accept TLS probe: {error}"),
                }
            }
        });

        let error = match minreq::get(format!("https://{address}/parameters")).send_lazy() {
            Ok(_) => panic!("probe server cannot complete TLS"),
            Err(error) => error,
        };
        let client_hello = client_hello_receiver
            .recv_timeout(ACCEPT_TIMEOUT)
            .expect("TLS probe must report a verdict")
            .unwrap_or_else(|| {
                panic!("the HTTPS feature must reach the local TLS server; error was {error:?}")
            });
        assert!(
            client_hello.starts_with(TLS_CLIENT_HELLO_PREFIX),
            "the HTTPS feature must send a TLS ClientHello"
        );
        server.join().expect("join TLS probe server");
    }
}
