import socket
import threading
import json
import time

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except:
        local_ip = "127.0.0.1"
    finally:
        s.close()
    return local_ip

MULTICAST_GROUP = '224.1.1.1' 
MULTICAST_PORT = 5007
PEER_PORT_BASE = 50000 
HEARTBEAT_TIMEOUT = 5 
HEARTBEAT_INTERVAL = 2 

class Peer:
    next_id = 1 
    
    def __init__(self, real_ip, my_port, name):
        self.real_ip = real_ip  
        self.my_port = my_port
        self.name = name 
        self.id = None 
        self.coordinator_id = None
        self.peers = {} 
        self.history = [] 
        self.is_coordinator = False
        self.last_heartbeat_time = time.time()
        self.running = True

        self.vector_clock = {} 
        self.pending_messages = [] 

        self.peer_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.peer_socket.bind(('0.0.0.0', self.my_port)) 
        
        self.election_in_progress = False

    def multicast_listener(self):
        if not self.is_coordinator:
            return

        print("Coordenador: Iniciando escuta de JOINs via Multicast...")
        
        multicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        multicast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        multicast_sock.bind(('0.0.0.0', MULTICAST_PORT)) 
        
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(self.real_ip)
        multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        while self.running and self.is_coordinator:
            try:
                multicast_sock.settimeout(1) 
                raw_data, addr = multicast_sock.recvfrom(1024)
                data = json.loads(raw_data.decode('utf-8'))
                
                if data.get('type') == 'JOIN':
                    threading.Thread(target=self.handle_join_request, args=(data,), daemon=True).start()
                    
            except socket.timeout:
                pass
            except Exception:
                pass 

        multicast_sock.close()


    def handle_join_request(self, data):
        if not self.is_coordinator:
            return

        peer_ip = data['ip']
        peer_port = data['port']
        peer_name = data['name']
        
        new_id = Peer.next_id
        is_new = True
        
        for id, (ip, port, name) in self.peers.items():
            if ip == peer_ip and port == peer_port:
                new_id = id
                is_new = False
                break
        
        if is_new:
            Peer.next_id += 1
            print(f"Coordenador: Novo nó ({peer_name}) em {peer_ip}:{peer_port}. Atribuindo ID: {new_id}")
        
        self.peers[new_id] = (peer_ip, peer_port, peer_name)
        
        if is_new:
            self.vector_clock[self.id] = self.vector_clock.get(self.id, 0) + 1

        welcome_msg = {
            'type': 'WELCOME',
            'assigned_id': new_id,
            'coordinator_id': self.id,
            'peers': self.peers,
            'vector_clock': self.vector_clock.copy() 
        }
        self.send_p2p_message(peer_ip, peer_port, welcome_msg)

        if is_new:
            self.broadcast_peer_update_internal()

    def join_network(self):
        print(f"Tentando entrar na rede via multicast...")
        
        join_msg = json.dumps({
            'type': 'JOIN',
            'ip': self.real_ip, 
            'port': self.my_port,
            'name': self.name
        }).encode('utf-8')
        
        multicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
        
        multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.real_ip))
        
        multicast_sock.sendto(join_msg, (MULTICAST_GROUP, MULTICAST_PORT))

        multicast_sock.settimeout(10) 
        try:
            data, address = multicast_sock.recvfrom(1024)
            self.handle_message(data)
        except socket.timeout:
            print("Timeout. Coordenador não encontrado. Iniciando Eleição...")
            
            if self.id is None:
                self.id = 1 
                self.peers[self.id] = (self.real_ip, self.my_port, self.name)
            
            self.start_election() 
        finally:
            multicast_sock.close()


    def send_heartbeats(self):
        while self.is_coordinator and self.running:
            heartbeat_msg = {'type': 'HEARTBEAT', 'coordinator_id': self.id}
            
            for peer_id, (ip, port, name) in self.peers.items():
                if peer_id != self.id:
                    self.send_p2p_message(ip, port, heartbeat_msg)
            
            time.sleep(HEARTBEAT_INTERVAL)


    def check_coordinator_liveness(self):
        if not self.running: return
        if self.is_coordinator: pass
        
        elif self.coordinator_id is not None:
            time_since_heartbeat = time.time() - self.last_heartbeat_time
            if time_since_heartbeat > HEARTBEAT_TIMEOUT:
                print(f"!!! Coordenador {self.coordinator_id} falhou. Iniciando Eleição!!!")
                self.coordinator_id = None
                self.start_election()
        
        if self.running:
            threading.Timer(1, self.check_coordinator_liveness).start()


    def start_election(self):
        
        if self.id is None or self.election_in_progress:
            return

        self.election_in_progress = True
        
        higher_peers = [peer_id for peer_id in self.peers.keys() if peer_id > self.id]
        
        if not higher_peers:
            self.proclaim_coordinator()
            return
        
        print("Eleição: Enviando ELECTION para nós com ID maior...")
        for peer_id_int in higher_peers:
            ip, port, _ = self.peers.get(peer_id_int)
            if ip and port:
                self.send_p2p_message(ip, port, {'type': 'ELECTION', 'sender_id': self.id})

        time.sleep(3) 
        
        if self.coordinator_id is None: 
            self.proclaim_coordinator()
        
        self.election_in_progress = False
            
    def proclaim_coordinator(self):
        self.is_coordinator = True
        self.coordinator_id = self.id
        
        Peer.next_id = max(self.peers.keys()) + 1 
        
        self.vector_clock[self.id] = self.vector_clock.get(self.id, 0) + 1
        
        print(f"--- SUCESSO: EU SOU O NOVO COORDENADOR ({self.name}): ID {self.id} ---")
        
        coordinator_msg = {
            'type': 'COORDINATOR', 
            'new_coordinator_id': self.id,
            'vector_clock': self.vector_clock.copy()
        }
        for peer_id, (ip, port, name) in self.peers.items():
            if peer_id != self.id:
                self.send_p2p_message(ip, port, coordinator_msg)
        
        threading.Thread(target=self.multicast_listener, daemon=True).start()
        threading.Thread(target=self.send_heartbeats, daemon=True).start()

    def initialize_vector_clock(self, peers_list):
        new_clock = {}
        for peer_id in peers_list.keys():
            new_clock[peer_id] = self.vector_clock.get(peer_id, 0)
        self.vector_clock = new_clock

    def can_deliver(self, sender_id, sender_clock):
        if sender_clock.get(sender_id, 0) != self.vector_clock.get(sender_id, 0) + 1:
            return False

        for peer_id in self.vector_clock.keys():
            if peer_id != sender_id:
                if sender_clock.get(peer_id, 0) > self.vector_clock.get(peer_id, 0):
                    return False
                    
        return True

    def deliver_message(self, sender_id, content, sender_clock):
        
        for peer_id in self.vector_clock.keys():
            self.vector_clock[peer_id] = max(
                self.vector_clock.get(peer_id, 0), 
                sender_clock.get(peer_id, 0)
            )

        sender_name = str(sender_id)
        if sender_id in self.peers:
            sender_name = self.peers[sender_id][2]
        
        msg = f"[{sender_name} | ID {sender_id}] {content} (VC: {self.vector_clock})"
        self.history.append(msg)
        print(f"\n[CHAT] {msg}")
        
        self.check_pending_messages()

    def check_pending_messages(self):
        delivered_count = 0
        new_pending_messages = [] 
        
        for msg_data in self.pending_messages:
            sender_id = msg_data['sender_id']
            sender_clock = msg_data['vector_clock']

            if self.can_deliver(sender_id, sender_clock):
                self.deliver_message(sender_id, msg_data['content'], sender_clock)
                delivered_count += 1
            else:
                new_pending_messages.append(msg_data)
                
        self.pending_messages = new_pending_messages
        
        if delivered_count > 0:
            print(f"(Entregues {delivered_count} mensagens pendentes)")

    def send_p2p_message(self, ip, port, message_data):
        try:
            msg = json.dumps(message_data).encode('utf-8')
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(msg, (ip, port))
            sock.close()
        except Exception:
            pass

    def broadcast_message(self, content):
        if self.id is None:
            print("Erro: Nó não registrado na rede.")
            return

        self.vector_clock[self.id] = self.vector_clock.get(self.id, 0) + 1
        
        chat_msg_data = {
            'type': 'CHAT',
            'sender_id': self.id,
            'content': content,
            'vector_clock': self.vector_clock.copy() 
        }

        print(f"[EU - {self.name}] Mensagem enviada: {content}")
        
        for peer_id, (ip, port, name) in self.peers.items():
            if peer_id != self.id:
                 self.send_p2p_message(ip, port, chat_msg_data)

    def broadcast_peer_update_internal(self, leaving_id=None):
        if not self.is_coordinator:
            return
            
        if leaving_id is not None:
            leaving_name = self.peers.get(leaving_id)[2] if self.peers.get(leaving_id) else str(leaving_id)
            print(f"Coordenador: Anunciando saída do nó {leaving_name} (ID {leaving_id}).")
            if leaving_id in self.peers:
                 del self.peers[leaving_id]
        
        self.vector_clock[self.id] = self.vector_clock.get(self.id, 0) + 1
        
        update_msg = {
            'type': 'PEER_UPDATE', 
            'peers': self.peers,
            'vector_clock': self.vector_clock.copy() 
        }
        
        for peer_id, (ip, port, name) in self.peers.items():
            if peer_id != self.id:
                self.send_p2p_message(ip, port, update_msg)

    def handle_message(self, raw_data):
        try:
            data = json.loads(raw_data.decode('utf-8'))
            msg_type = data.get('type')

            if msg_type == 'WELCOME':
                self.id = data['assigned_id']
                self.coordinator_id = data['coordinator_id']
                self.peers = {int(k): tuple(v) for k, v in data['peers'].items()}
                self.is_coordinator = (self.id == self.coordinator_id)
                
                sender_clock = {int(k): v for k, v in data['vector_clock'].items()}
                for peer_id in self.peers.keys():
                    self.vector_clock[peer_id] = max(
                        self.vector_clock.get(peer_id, 0), 
                        sender_clock.get(peer_id, 0)
                    )
                
                self.initialize_vector_clock(self.peers) 
                print(f"--- Registrado. Meu ID: {self.id}. Coordenador: {self.coordinator_id}. VC: {self.vector_clock}")
                
                self.election_in_progress = False
                self.check_coordinator_liveness()

            elif msg_type == 'HEARTBEAT' and data.get('coordinator_id') == self.coordinator_id:
                self.last_heartbeat_time = time.time()
            
            elif msg_type == 'ELECTION':
                sender_id = data['sender_id']
                if self.id is not None and self.id > sender_id:
                    ip, port, _ = self.peers.get(sender_id)
                    self.send_p2p_message(ip, port, {'type': 'OK', 'sender_id': self.id})
                    self.start_election() 
            elif msg_type == 'OK' and self.election_in_progress:
                self.election_in_progress = False 
            elif msg_type == 'COORDINATOR':
                self.coordinator_id = data['new_coordinator_id']
                self.is_coordinator = (self.id == self.coordinator_id)
                
                sender_clock = {int(k): v for k, v in data['vector_clock'].items()}
                for peer_id in self.peers.keys():
                    self.vector_clock[peer_id] = max(self.vector_clock.get(peer_id, 0), sender_clock.get(peer_id, 0))
                
                self.election_in_progress = False
                if self.is_coordinator:
                    threading.Thread(target=self.multicast_listener, daemon=True).start()
                    threading.Thread(target=self.send_heartbeats, daemon=True).start()
                print(f"--- Novo Coordenador eleito: {self.coordinator_id}")

            elif msg_type == 'PEER_UPDATE':
                self.peers = {int(k): tuple(v) for k, v in data['peers'].items()}
                
                sender_clock = {int(k): v for k, v in data['vector_clock'].items()}
                for peer_id in self.peers.keys():
                    self.vector_clock[peer_id] = max(self.vector_clock.get(peer_id, 0), sender_clock.get(peer_id, 0))

                self.initialize_vector_clock(self.peers) 
                print(f"--- Lista de nós atualizada. Nós Ativos: {self.peers.keys()}. VC: {self.vector_clock}")

            elif msg_type == 'LEAVE' and self.is_coordinator:
                self.broadcast_peer_update_internal(leaving_id=data['leaving_id'])

            elif msg_type == 'CHAT':
                sender_id = data['sender_id']
                sender_clock = {int(k): v for k, v in data['vector_clock'].items()} 

                if self.can_deliver(sender_id, sender_clock):
                    self.deliver_message(sender_id, data['content'], sender_clock)
                else:
                    self.pending_messages.append(data)

        except Exception:
            pass

    def listen_loop(self):
        while self.running:
            try:
                raw_data, addr = self.peer_socket.recvfrom(4096)
                threading.Thread(target=self.handle_message, args=(raw_data,), daemon=True).start()
            except socket.error:
                if self.running: pass
            except Exception:
                pass

    def start(self):
        listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        listen_thread.start()
        
        self.join_network()
        
    def stop(self):
        self.running = False
        
        if self.id is not None:
            if self.coordinator_id in self.peers and self.coordinator_id != self.id:
                ip, port, _ = self.peers[self.coordinator_id]
                self.send_p2p_message(ip, port, {'type': 'LEAVE', 'leaving_id': self.id})
        
        self.peer_socket.close()
        print(f"Nó {self.id} encerrado.")

if __name__ == '__main__':
    
    LOCAL_IP = get_local_ip() 
    print("Meu IP descoberto:", LOCAL_IP)
    
    name = input("Digite o NOME deste nó (ex: UsuarioA): ")
    
    try:
        peer_port = int(input(f"Digite a porta para este nó (ex: {PEER_PORT_BASE+1}): "))
    except ValueError:
        print("Porta inválida.")
        exit()

    peer = Peer(LOCAL_IP, peer_port, name)
    peer.start()

    try:
        while peer.running:
            command = input("\n[Comandos: 'chat <mensagem>', 'status', 'exit']\n> ")
            if command.lower().startswith("chat "):
                message = command[5:].strip()
                if message:
                    peer.broadcast_message(message)
            elif command.lower() == "status":
                print(f"--- Status do Nó {peer.id} ---")
                print(f"Nome: {peer.name}")
                print(f"Coordenador: {peer.coordinator_id} ({'EU' if peer.is_coordinator else 'OUTRO'})")
                print(f"Nós Ativos: {peer.peers.keys()}")
                print(f"Vector Clock: {peer.vector_clock}")
            elif command.lower() == "exit":
                peer.stop()
            else:
                print("Comando inválido.") 
            
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nInterrupção detectada.")
        peer.stop()