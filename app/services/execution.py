import docker
import uuid
import logging
import os
import shlex
import asyncio
from datetime import datetime
import shutil
import pty
import fcntl
import select
import signal
import termios
import sys
import errno

from app.core.config import settings

logger = logging.getLogger(__name__)


class CodeExecutionService:
    def __init__(self):
        # Check if we should use Docker based on environment variable
        self.use_docker = settings.USE_DOCKER
        self.client = None
        self.active_containers = {}
        self.active_sessions = {}
        self.workspace_root = settings.WORKSPACE_ROOT

        # Only initialize Docker client if we're using Docker
        if self.use_docker:
            try:
                self.client = docker.from_env()
                logger.info("Docker client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Docker client: {e}")
                self.use_docker = False

    async def create_session(self, language):
        """Create a new code execution session with interactive terminal"""
        # Generate unique session ID
        session_id = str(uuid.uuid4())

        if self.use_docker:
            # Docker-based execution
            return await self._create_docker_session(session_id, language)
        else:
            # Fallback: Process-based execution
            return await self._create_process_session(session_id, language)

    async def _create_docker_session(self, session_id, language):
        """Create a Docker-based execution session"""
        # Validate language support
        if language not in settings.LANGUAGE_IMAGES:
            raise ValueError(f"Unsupported language: {language}")

        image_name = settings.LANGUAGE_IMAGES[language]

        # Define container workspace path
        code_file_path = '/root/Code-Execution-Microservice/workspace'

        logger.info(f"Container workspace path: {code_file_path}")

        try:
            # Launch container with security constraints
            container = self.client.containers.run(
                image=image_name,
                detach=True,
                tty=True,
                stdin_open=True,
                volumes={
                    code_file_path: {
                        'bind': '/code',
                        'mode': 'rw'
                    }
                },
                working_dir='/code',
                # Resource limits
                mem_limit='256m',
                cpu_period=100000,
                cpu_quota=20000,  # 20% of CPU
                # Security settings
                cap_drop=['ALL'],
                security_opt=['no-new-privileges:true'],
                network_mode='none'
            )

            # Verify volume mounting worked
            exit_code, output = container.exec_run(f"ls -la {code_file_path}")
            logger.info(
                f"Initial container workspace: {output.decode('utf-8')}")

            # Store container information
            self.active_containers[session_id] = {
                'container': container,
                'language': language,
                'created_at': datetime.now()
            }

            logger.info(
                f"Created Docker session {session_id} for language {language}")
            return session_id

        except Exception as e:
            # Clean up workspace if creation failed
            if os.path.exists(code_file_path):
                shutil.rmtree(code_file_path)
            logger.error(f"Failed to create Docker session: {e}")
            raise ValueError(f"Failed to create Docker session: {str(e)}")

    async def _create_process_session(self, session_id, language):
        """Create a process-based execution session (fallback)"""
        # Create workspace directory for this session
        # workspace_path = f"{self.workspace_root}/workspace"
        workspace_path = '/root/Code-Execution-Microservice/workspace'
        os.makedirs(workspace_path, exist_ok=True)

        # Store session information
        self.active_sessions[session_id] = {
            'language': language,
            'created_at': datetime.now(),
            'workspace_path': workspace_path
        }

        logger.info(
            f"Created process-based session {session_id} for language {language}")
        return session_id

    async def execute_code(self, session_id, code, input_data=None, timeout=None):
        """Execute code in an existing session"""
        logger.debug("Entering execute_code (non-streaming)")
        # Set default timeout if not provided
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        # Validate session exists
        if session_id not in self.active_containers and session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found")

        # Handle Docker-based execution
        if self.use_docker and session_id in self.active_containers:
            container_info = self.active_containers[session_id]
            language = container_info['language']
            container = container_info['container']

            # Create or reuse code file for this session
            if 'code_path' not in container_info:
                file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
                code_filename = f"code_{uuid.uuid4().hex}.{file_ext}"
                code_dir = "./workspace"
                os.makedirs(code_dir, exist_ok=True)
                code_path = os.path.join(code_dir, code_filename)
                container_info['code_path'] = code_path
                logger.debug(f"Creating new code file: {code_path}")
            else:
                code_path = container_info['code_path']
                code_dir = os.path.dirname(code_path)
                code_filename = os.path.basename(code_path)
                logger.debug(f"Using existing code file: {code_path}")

            # Write code to file
            try:
                with open(code_path, "w") as f:
                    f.write(code)
                logger.debug(f"Successfully wrote code to file: {code_path}")
            except Exception as e:
                logger.error(f"Error writing code to file: {e}")
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': f"Error writing code file: {str(e)}"
                }

            if not os.path.exists(code_path):
                logger.error(f"Code file not created at: {code_path}")
                raise RuntimeError("Failed to create code file")

            # Prepare language-specific execution command
            if language == 'python':
                cmd = f"python /code/{code_filename}"

            elif language == 'cpp':
                compile_cmd = f"g++ /code/{code_filename} -o /code/a.out"
                run_cmd = f"/code/a.out"
                cmd = f"sh -c '{compile_cmd} && {run_cmd}'"

            elif language == 'c':
                compile_cmd = f"gcc /code/{code_filename} -o /code/a.out"
                run_cmd = f"/code/a.out"
                cmd = f"sh -c '{compile_cmd} && {run_cmd}'"

            logger.debug(f"Executing command in container: {cmd}")

            # Execute in container with timeout
            try:
                exit_code, output = container.exec_run(
                    cmd=cmd,
                    tty=True,
                    demux=True,  # Split stdout and stderr
                )

                # Process output
                stdout = output[0].decode('utf-8') if output[0] else ""
                stderr = output[1].decode('utf-8') if output[1] else ""

                return {
                    'exit_code': exit_code,
                    'output': stdout,
                    'error': stderr if stderr else None
                }
            except Exception as e:
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': str(e)
                }

    def _has_input_requirements(self, code, language):
        """Check if code likely requires user input based on language"""
        # Language-specific input detection patterns
        if language == 'python':
            has_input = "input(" in code
            logger.info(f"Python code input requirements check: {has_input}")
            return has_input
        elif language == 'javascript':
            return "prompt(" in code or "readline" in code or "process.stdin" in code
        elif language == 'java':
            return "Scanner" in code or "readLine" in code or "System.console" in code
        elif language == 'cpp':
            return "cin" in code or "getline" in code or "scanf" in code
        elif language == 'c':
            return "scanf" in code or "getchar" in code or "gets" in code
        elif language == 'ruby':
            return "gets" in code or "readline" in code
        elif language == 'csharp':
            return "Console.Read" in code or "ReadLine" in code
        # For any unsupported language, default to false
        return False

    async def execute_code_with_streaming(self, session_id, code, input_data=None, timeout=None, callback=None):
        logger.debug("Entering execute_code_with_streaming")

        # Set default timeout if not provided
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        logger.debug(f"Session ID: {session_id}, Timeout: {timeout}")

        # Validate session exists
        if session_id not in self.active_containers and session_id not in self.active_sessions:
            logger.error(f"Session {session_id} not found")
            raise ValueError(f"Session {session_id} not found")

        logger.debug("Session found in active containers or sessions")

        # For now, just execute and send the complete result through callback
        result = await self.execute_code(session_id, code, input_data, timeout)

        # Send results via callback if provided
        if callback:
            await callback({
                'output': result['output'],
                'error': result['error'],
                'exit_code': result['exit_code'],
                'complete': True
            })

        return result

    async def terminate_session(self, session_id):
        """Terminate an execution session and clean up resources"""
        # Handle Docker-based session termination
        if session_id in self.active_containers:
            try:
                container_info = self.active_containers[session_id]
                container = container_info['container']

                # Stop and remove the container
                container.stop(timeout=2)
                container.remove(force=True)

                # Remove session from active containers
                del self.active_containers[session_id]

                # Clean up workspace
                workspace_path = f"{self.workspace_root}/{session_id}"
                if os.path.exists(workspace_path):
                    shutil.rmtree(workspace_path)

                logger.info(f"Terminated Docker session {session_id}")
                return True
            except Exception as e:
                logger.error(
                    f"Error terminating Docker session {session_id}: {e}")
                return False
        # Handle process-based session termination
        elif session_id in self.active_sessions:
            try:
                # Clean up workspace
                workspace_path = self.active_sessions[session_id]['workspace_path']
                if os.path.exists(workspace_path):
                    shutil.rmtree(workspace_path)

                # Remove session
                del self.active_sessions[session_id]

                logger.info(f"Terminated process session {session_id}")
                return True
            except Exception as e:
                logger.error(
                    f"Error terminating process session {session_id}: {e}")
                return False
        else:
            logger.warning(f"Session {session_id} not found for termination")
            return False

    async def _handle_interactive_input(self, session_id, fifo_path, container_info, callback):
        """Handle interactive input via named pipe to container"""
        # Initialize input queue if not exists
        if 'input_queue' not in container_info:
            container_info['input_queue'] = asyncio.Queue()

        input_queue = container_info['input_queue']

        try:
            # Open the fifo for writing in non-blocking mode
            fifo = open(fifo_path, 'w')

            while True:
                # Wait for input to become available
                logger.debug(f"Waiting for input for session {session_id}")
                input_data = await input_queue.get()
                logger.debug(f"Received input: {input_data}")

                # Write input to the fifo
                fifo.write(f"{input_data}\n")
                fifo.flush()

                # Notify the client that input was processed
                if callback:
                    await callback({
                        'input_processed': True,
                        'complete': False
                    })

        except Exception as e:
            logger.error(f"Error in interactive input handling: {e}")
        finally:
            try:
                fifo.close()
            except:
                pass

    async def _stream_container_output(self, exec_id, container, callback):
        """Stream output from a container execution"""
        output_buffer = ""
        waiting_for_input = False

        # Get the output stream from the exec
        for chunk in exec_id.output:
            if chunk:
                try:
                    # Decode the output chunk
                    chunk_output = chunk.decode('utf-8')
                    output_buffer += chunk_output

                    # Check if this might be an input prompt
                    if (chunk_output.endswith(': ') or
                        chunk_output.endswith('? ') or
                        'input' in chunk_output.lower() or
                            'enter' in chunk_output.lower()):
                        waiting_for_input = True

                    # Send the output chunk through callback
                    if callback:
                        await callback({
                            'output': chunk_output,
                            'waiting_for_input': waiting_for_input,
                            'complete': False,
                            'exit_code': None,
                            'error': None
                        })

                    # Yield the chunk so the caller can process it too if needed
                    yield chunk_output

                    # If we detected an input prompt, pause here until input is provided
                    if waiting_for_input:
                        # The input will be handled by _handle_interactive_input
                        # This just pauses output processing until more output is available
                        await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error processing container output: {e}")
                    if callback:
                        await callback({
                            'output': '',
                            'complete': False,
                            'exit_code': None,
                            'error': f"Error processing output: {str(e)}"
                        })

        # Send completion notification
        if callback:
            await callback({
                'output': '',
                'complete': True,
                'exit_code': 0,  # We don't know the exact exit code in streaming mode
                'error': None
            })

    async def execute_code_with_pty(self, session_id, code, timeout=None, callback=None):
        """Execute code in a pseudo-terminal for proper input handling"""
        logger.debug("Entering execute_code_with_pty")

        # Set default timeout if not provided
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        # Validate session exists
        if session_id not in self.active_containers and session_id not in self.active_sessions:
            logger.error(f"Session {session_id} not found")
            raise ValueError(f"Session {session_id} not found")

        # Use Docker container: if not, we return an error since streaming mode supports only Docker-based execution
        if session_id in self.active_containers:
            container_info = self.active_containers[session_id]
            language = container_info['language']
            container = container_info['container']
            logger.debug(
                f"Using Docker container for session {session_id}, language: {language}")
        else:
            logger.error(
                f"Session {session_id} should be in Docker containers but wasn't found.")
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Session {session_id} not found in Docker containers for streaming execution."
            }

        # Create or reuse code file for this session
        if 'code_path' not in container_info:
            file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
            code_filename = f"code_main.{file_ext}"
            code_dir = "./workspace"
            os.makedirs(code_dir, exist_ok=True)
            code_path = os.path.join(code_dir, code_filename)
            container_info['code_path'] = code_path
            logger.debug(f"Creating new code file: {code_path}")
        else:
            code_path = container_info['code_path']
            code_dir = os.path.dirname(code_path)
            code_filename = os.path.basename(code_path)
            logger.debug(f"Using existing code file: {code_path}")

        # Write code to file
        try:
            with open(code_path, "w") as f:
                f.write(code)
            logger.debug(f"Successfully wrote code to file: {code_path}")
        except Exception as e:
            logger.error(f"Error writing code to file: {e}")
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Error writing code file: {str(e)}"
            }

        # Prepare language-specific command
        if language == 'python':
            cmd = f"python {code_path}"
        elif language == 'javascript':
            cmd = f"node {code_path}"
        else:
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Language {language} not supported in PTY mode"
            }

        # Create pseudo-terminal
        master, slave = pty.openpty()

        # Set terminal to raw mode (no echo, no line buffering)
        old_attr = termios.tcgetattr(slave)
        new_attr = termios.tcgetattr(slave)
        new_attr[3] = new_attr[3] & ~termios.ECHO & ~termios.ICANON
        termios.tcsetattr(slave, termios.TCSANOW, new_attr)

        # Make the master end non-blocking
        fl = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        # Start the process in the PTY
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True
            )
            os.close(slave)
        except Exception as e:
            logger.error(f"Error launching subprocess in PTY: {e}")
            if callback:
                await callback({
                    'output': "",
                    'complete': True,
                    'exit_code': 1,
                    'error': f"Error creating PTY: {str(e)}"
                })
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Error creating PTY: {str(e)}"
            }

        output_buffer = ""
        waiting_for_input = False

        # Ensure there's an input queue
        if 'input_queue' not in container_info:
            container_info['input_queue'] = asyncio.Queue()

        input_queue = container_info['input_queue']

        async def read_output():
            """Read output from the PTY and send it to the callback"""
            nonlocal output_buffer, waiting_for_input
            try:
                # Check if there's data to read from the PTY
                r, w, e = select.select([master], [], [master], 0.1)
                if master in r:
                    chunk = os.read(master, 1024)
                    if chunk:
                        output = chunk.decode('utf-8', errors='replace')
                        output_buffer += output
                        logger.debug(f"PTY output: {output.strip()}")

                        # Check if code might be waiting for input
                        if self._has_input_requirements(code, language):
                            waiting_for_input = True
                            # Send input request to the callback
                        if callback:
                            await callback({
                                'output': output,
                                'waiting_for_input': waiting_for_input,
                                'complete': False,
                                'exit_code': None,
                                'error': None
                            })
                        return True
            except OSError as e:
                if e.errno != errno.EAGAIN:
                    logger.error(f"Error reading PTY output: {e}")
            return False

        # Main loop to read output and handle input
        try:
            while process.returncode is None:
                await read_output()

                # Handle user input if program is waiting for it
                if waiting_for_input:
                    logger.debug(f"Waiting for input from user...")
                    user_input = await input_queue.get()
                    logger.debug(f"Received input: {user_input}")

                    # Send input to the PTY
                    os.write(master, f"{user_input}\n".encode('utf-8'))

                    await asyncio.sleep(0.2)

                    if callback:
                        await callback({
                            'output': f"{user_input}\n",
                            'waiting_for_input': False,
                            'complete': False,
                            'exit_code': None,
                            'error': None
                        })

                    waiting_for_input = False

            # Give time for final output to be processed
            await asyncio.sleep(0.05)
            await asyncio.sleep(0.05)
            if process.returncode is not None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass

            # Read any remaining output
            while await read_output():
                pass

            # Send completion notification
            if callback:
                await callback({
                    'output': '',
                    'waiting_for_input': False,
                    'complete': True,
                    'exit_code': process.returncode or 0,
                    'error': None if process.returncode == 0 else f"Process returned with exit code {process.returncode}"
                })

            return {
                'exit_code': process.returncode or 0,
                'output': output_buffer,
                'error': None if process.returncode == 0 else f"Process returned with exit code {process.returncode}"
            }
        except Exception as e:
            logger.error(f"Error in PTY execution: {e}")
            if callback:
                await callback({
                    'output': '',
                    'complete': True,
                    'exit_code': 1,
                    'error': f"Error in PTY execution: {str(e)}"
                })
            return {
                'exit_code': 1,
                'output': '',
                'error': f"Error in PTY execution: {str(e)}"
            }
        finally:
            # Clean up resources
            try:
                os.close(master)
            except:
                pass
            try:
                if process and process.returncode is None:
                    process.kill()
            except:
                pass



# Create a singleton instance
execution_service = CodeExecutionService()
