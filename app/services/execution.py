import docker
import uuid
import logging
import os
import shlex
import asyncio
from datetime import datetime
import shutil

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
        session_id = str(uuid.uuid4())

        if self.use_docker:
            # Docker-based execution
            return await self._create_docker_session(session_id, language)
        else:
            # Fallback: Process-based execution
            return await self._create_process_session(session_id, language)

    async def _create_docker_session(self, session_id, language):
        """Create a Docker-based execution session"""
        if language not in settings.LANGUAGE_IMAGES:
            raise ValueError(f"Unsupported language: {language}")

        image_name = settings.LANGUAGE_IMAGES[language]

        # The container will see the same directory at:
        code_file_path = '/root/Code-Execution-Microservice/workspace'

        logger.info(f"Container workspace path: {code_file_path}")

        try:
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
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        if session_id not in self.active_containers and session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found")

        if self.use_docker and session_id in self.active_containers:
            container_info = self.active_containers[session_id]
            language = container_info['language']
            container = container_info['container']

            # Use the existing code file or create a new one if needed
            if 'code_path' not in container_info:
                # First execution for this session, create the code file
                file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
                code_filename = f"code_{uuid.uuid4().hex}.{file_ext}"
                code_dir = "./workspace"
                os.makedirs(code_dir, exist_ok=True)
                code_path = os.path.join(code_dir, code_filename)
                container_info['code_path'] = code_path
            else:
                # Use the existing code file
                code_path = container_info['code_path']
                code_dir = "./workspace"
                code_filename = os.path.basename(code_path)

            with open(code_path, "w") as f:
                f.write(code)

            logger.info(f"Successfully wrote code file to: {code_path}")

            # Write input data to a temporary file if provided
            if input_data:
                input_filename = f"input_{uuid.uuid4().hex}.txt"
                input_path = os.path.join(code_dir, input_filename)
                with open(input_path, "w") as f:
                    f.write(input_data)
                logger.info(f"Successfully wrote input file to: {input_path}")
            else:
                input_filename = None

            if not os.path.exists(code_path):
                logger.error(f"Code file not created at: {code_path}")
                raise RuntimeError("Failed to create code file")

            # Prepare the command based on language
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

                # Clean up temporary files after execution
                os.remove(code_path)
                if input_filename:
                    os.remove(input_path)

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

        """Execute code using a subprocess (fallback method)"""
        session_info = self.active_sessions[session_id]
        language = session_info['language']
        workspace_path = session_info['workspace_path']

        # Create code file
        file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
        code_path = f"{workspace_path}/code.{file_ext}"

        with open(code_path, "w") as f:
            f.write(code)

        # Create temporary input file if needed
        input_path = None
        if input_data:
            input_path = f"{workspace_path}/input.txt"
            with open(input_path, "w") as f:
                f.write(input_data)

        # Prepare the command based on language
        if language == 'python':
            cmd = ["python", code_path]
        elif language == 'javascript':
            cmd = ["node", code_path]
        else:
            # Fallback for unsupported languages in process mode
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Language {language} not supported in process mode"
            }

        # Execute the code
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Set up timeout
            try:
                if input_data:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(input=input_data.encode()),
                        timeout=timeout
                    )
                else:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )

                return {
                    'exit_code': process.returncode,
                    'output': stdout.decode(),
                    'error': stderr.decode() if stderr else None
                }
            except asyncio.TimeoutError:
                # Kill the process if it times out
                process.kill()
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': f"Execution timed out after {timeout} seconds"
                }

        except Exception as e:
            return {
                'exit_code': 1,
                'output': "",
                'error': str(e)
            }

    def _has_input_requirements(self, code, language):
        """Check if code likely requires user input based on language"""
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
        """Execute code with streaming output via callback"""
        logger.debug("Entering execute_code_with_streaming")

        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        logger.debug(f"Session ID: {session_id}, Timeout: {timeout}")

        if session_id not in self.active_containers and session_id not in self.active_sessions:
            logger.error(f"Session {session_id} not found")
            raise ValueError(f"Session {session_id} not found")

        logger.debug("Session found in active containers or sessions")

        # Get the language and container info
        if session_id in self.active_containers:
            container_info = self.active_containers[session_id]
            language = container_info['language']
            container = container_info['container']
            logger.debug(
                f"Using Docker container for session {session_id}, language: {language}")
        else:
            logger.error(
                f"Session {session_id} should be in Docker containers but wasn't found.")
            return {  # Returning here as fallback to process based execution is removed in streaming mode
                'exit_code': 1,
                'output': "",
                'error': f"Session {session_id} not found in Docker containers for streaming execution."
            }

        # Use the existing code file or create a new one if needed
        if 'code_path' not in container_info:
            # First execution for this session, create the code file
            file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
            code_filename = f"code_main.{file_ext}"
            code_dir = "/code"  # Changed to /code to match container's workspace
            os.makedirs(code_dir, exist_ok=True)
            code_path = os.path.join(code_dir, code_filename)
            container_info['code_path'] = code_path
            logger.debug(f"Creating new code file: {code_path}")
        else:
            # Use the existing code file
            code_path = container_info['code_path']
            # Ensure code_dir is correctly set
            code_dir = os.path.dirname(code_path)
            code_filename = os.path.basename(code_path)
            logger.debug(f"Using existing code file: {code_path}")

        # Write the updated code to the file
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

        # Check if code might need interactive input
        has_input_calls = self._has_input_requirements(code, language)
        logger.debug(
            f"Input requirements check - has_input_calls: {has_input_calls}")

        if has_input_calls:
            logger.debug(
                "Code has input calls, setting up interactive input handling")
            # Create a queue to handle interactive input
            input_queue = asyncio.Queue()

            # Execute with interactive input handling
            if language == 'python':
                cmd = f"python {code_path}"  # Using full path
                logger.debug(f"Python command: {cmd}")
            elif language == 'cpp':
                compile_cmd = ["g++", code_path, "-o", f"{code_dir}/a.out"]
                logger.debug(f"C++ compile command: {compile_cmd}")
                try:
                    compile_process = await asyncio.create_subprocess_exec(
                        *compile_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    logger.debug("C++ compilation process started")
                    _, stderr = await compile_process.communicate()
                    if compile_process.returncode != 0:
                        logger.error(
                            f"C++ compilation failed, exit code: {compile_process.returncode}, stderr: {stderr.decode()}")
                        if callback:
                            await callback({
                                'output': '',
                                'complete': True,
                                'exit_code': compile_process.returncode,
                                'error': stderr.decode()
                            })
                        return {
                            'exit_code': compile_process.returncode,
                            'output': '',
                            'error': stderr.decode()
                        }
                    cmd = [f"{code_dir}/a.out"]
                    logger.debug(f"C++ run command: {cmd}")
                except Exception as e:
                    logger.exception("Exception during C++ compilation")
                    if callback:
                        await callback({
                            'output': '',
                            'complete': True,
                            'exit_code': 1,
                            'error': f"Compilation error: {str(e)}"
                        })
                    return {
                        'exit_code': 1,
                        'output': '',
                        'error': f"Compilation error: {str(e)}"
                    }
            elif language == 'c':
                compile_cmd = ["gcc", code_path, "-o", f"{code_dir}/a.out"]
                logger.debug(f"C compile command: {compile_cmd}")
                try:
                    compile_process = await asyncio.create_subprocess_exec(
                        *compile_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    logger.debug("C compilation process started")
                    _, stderr = await compile_process.communicate()
                    if compile_process.returncode != 0:
                        logger.error(
                            f"C compilation failed, exit code: {compile_process.returncode}, stderr: {stderr.decode()}")
                        if callback:
                            await callback({
                                'output': '',
                                'complete': True,
                                'exit_code': compile_process.returncode,
                                'error': stderr.decode()
                            })
                        return {
                            'exit_code': compile_process.returncode,
                            'output': '',
                            'error': stderr.decode()
                        }
                    cmd = [f"{code_dir}/a.out"]
                    logger.debug(f"C run command: {cmd}")
                except Exception as e:
                    logger.exception("Exception during C compilation")
                    if callback:
                        await callback({
                            'output': '',
                            'complete': True,
                            'exit_code': 1,
                            'error': f"Compilation error: {str(e)}"
                        })
                    return {
                        'exit_code': 1,
                        'output': '',
                        'error': f"Compilation error: {str(e)}"
                    }
            else:
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': f"Language {language} not supported in streaming mode"
                }

            logger.debug(f"Executing code command: {cmd}")
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                logger.debug("Subprocess created successfully")
            except Exception as e:
                logger.exception("Error creating subprocess")
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': f"Error creating subprocess: {str(e)}"
                }

            logger.debug("Before read_output definition")

            async def read_output():
                nonlocal output_buffer, has_output
                # Log when read_output is entered
                logger.debug("Entering read_output")
                line = await process.stdout.readline()
                if line:
                    output = line.decode('utf-8')
                    output_buffer += output
                    logger.debug(f"Read output chunk: {output.strip()}")
                    if callback:
                        await callback({
                            'output': output,
                            'complete': False,
                            'exit_code': None,
                            'error': None
                        })
                    has_output = True
                    # Log before exiting
                    logger.debug("Exiting read_output - has_output=True")
                else:
                    has_output = False
                    # Log when no output
                    logger.debug(
                        "No more output to read in read_output - has_output=False")
                # Log when read_output is exited
                logger.debug("Exiting read_output")
                return has_output

            logger.debug("After read_output definition")

            output_buffer = ""
            has_output = True
            waiting_for_input = False

            logger.debug("Entering main execution while loop")
            while process.returncode is None:
                # Start of loop iteration log
                logger.debug("--- While loop iteration start ---")
                if waiting_for_input:
                    logger.debug("Waiting for input...")
                    try:
                        user_input = await asyncio.wait_for(input_queue.get(), timeout=timeout)
                        logger.debug(f"Received user input: {user_input}")
                        process.stdin.write(f"{user_input}\n".encode())
                        await process.stdin.drain()
                        waiting_for_input = False
                        await read_output()
                    except asyncio.TimeoutError:
                        logger.warning("Input timeout exceeded")
                        process.kill()
                        if callback:
                            await callback({
                                'output': '\nInput timeout exceeded',
                                'complete': True,
                                'exit_code': 1,
                                'error': 'Timeout waiting for input'
                            })
                        return {
                            'exit_code': 1,
                            'output': output_buffer + '\nInput timeout exceeded',
                            'error': 'Timeout waiting for input'
                        }
                elif has_output:
                    logger.debug("has_output is True, calling read_output")
                    has_output = await read_output()
                    logger.debug(
                        f"read_output returned, has_output is now: {has_output}")
                else:
                    logger.debug("has_output is False, waiting for process...")
                    try:
                        await asyncio.wait_for(process.wait(), timeout=0.5)
                    except asyncio.TimeoutError:
                        logger.debug(
                            "Short timeout in process.wait() expired, continuing loop")
                        continue
                # End of loop iteration log
                logger.debug("--- While loop iteration end ---")

            # Read any remaining output
            logger.debug("Process finished, reading remaining output")
            stdout, stderr = await process.communicate()
            final_output = stdout.decode()
            output_buffer += final_output
            error = stderr.decode() if stderr else None

            logger.debug(f"Final output: {final_output.strip()}")
            logger.debug(f"Error output: {error.strip() if error else None}")
            logger.debug(f"Exit code: {process.returncode}")

            if callback:
                await callback({
                    'output': final_output,
                    'complete': True,
                    'exit_code': process.returncode,
                    'error': error
                })

            return {
                'exit_code': process.returncode,
                'output': output_buffer,
                'error': error
            }

        else:
            logger.debug(
                "Code does not have input calls, using standard execute_code method")
            # For code without input or Docker-based execution, use the standard method
            result = await self.execute_code(session_id, code, input_data, timeout)

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
        if session_id in self.active_containers:
            # Docker-based session
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
        elif session_id in self.active_sessions:
            # Process-based session
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


# Create a singleton instance
execution_service = CodeExecutionService()
