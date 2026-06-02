import sys
import subprocess
import ipaddress
import dns.resolver

def ping_host(host: str) -> str:
    """
    Pings a host or domain name to check if it's reachable and measure roundtrip latency.
    Use this tool when the user asks you to ping, check latency, or verify if a domain/IP is online.
    
    Args:
        host: The IP address or domain name to ping (e.g. '8.8.8.8' or 'google.com').
        
    Returns:
        The output result of the ping command or an error message.
    """
    # Clean the host input to prevent command injection
    host = host.strip().split()[0]
    
    # Set parameter based on OS (Windows vs Linux/Mac)
    param = "-n" if sys.platform.lower().startswith("win") else "-c"
    command = ["ping", param, "3", host]
    
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        if result.returncode == 0:
            return f"Ping successful to {host}:\n{result.stdout}"
        else:
            return f"Ping failed to {host}:\n{result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return f"Ping timed out to {host}"
    except Exception as e:
        return f"Error executing ping to {host}: {e}"

def dns_lookup(domain: str, record_type: str = "A") -> str:
    """
    Queries DNS records for a given domain name.
    Use this tool when the user asks for DNS records, MX records, TXT verification, nameservers, or IP lookup for a domain.
    
    Args:
        domain: The domain name to query (e.g. 'gmail.com' or 'google.com').
        record_type: The type of DNS record to query (e.g. 'A', 'AAAA', 'MX', 'TXT', 'NS', 'CNAME', 'SOA'). Defaults to 'A'.
        
    Returns:
        The list of queried DNS records or an error message.
    """
    domain = domain.strip().split()[0]
    record_type = record_type.strip().upper()
    
    valid_types = ["A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA"]
    if record_type not in valid_types:
        return f"Invalid DNS record type. Valid types are: {', '.join(valid_types)}"
        
    try:
        answers = dns.resolver.resolve(domain, record_type)
        results = []
        for rdata in answers:
            results.append(str(rdata))
        return f"DNS query ({record_type}) for {domain} returned:\n" + "\n".join(f"- {r}" for r in results)
    except Exception as e:
        return f"Error querying DNS ({record_type}) for {domain}: {e}"

def subnet_calculator(ip_with_cidr: str) -> str:
    """
    Parses an IP address with CIDR notation and calculates the network details (subnet ranges, masks, usable hosts).
    Use this tool when the user asks to calculate subnets, CIDR notations, subnet masks, or network range details.
    
    Args:
        ip_with_cidr: The IP address with CIDR block (e.g. '192.168.1.0/24' or '10.0.0.0/22').
        
    Returns:
        Subnet statistics and calculations.
    """
    try:
        network = ipaddress.ip_network(ip_with_cidr.strip(), strict=False)
        num_hosts = network.num_addresses - 2 if network.prefixlen < 31 else network.num_addresses
        
        info = [
            f"Subnet details for {ip_with_cidr}:",
            f"- Network address: {network.network_address}",
            f"- Netmask: {network.netmask}",
            f"- Prefix length: /{network.prefixlen}",
            f"- Broadcast address: {network.broadcast_address if network.prefixlen < 31 else 'N/A'}",
            f"- First usable host: {network.network_address + 1 if network.prefixlen < 31 else network.network_address}",
            f"- Last usable host: {network.broadcast_address - 1 if network.prefixlen < 31 else network.broadcast_address}",
            f"- Total usable hosts: {num_hosts if num_hosts > 0 else 0}"
        ]
        return "\n".join(info)
    except Exception as e:
        return f"Error calculating subnet for {ip_with_cidr}: {e}"
