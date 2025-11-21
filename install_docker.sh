#!/bin/bash

# --- Check if the script is run as root user ---
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run with sudo." 
   echo "Please execute: sudo ./install_docker.sh"
   exit 1
fi

echo "--- 1. Update package index and install dependencies ---"
apt update
apt install -y ca-certificates curl gnupg lsb-release

echo "--- 2. Add Docker's official GPG key ---"
# Create keyrings directory
sudo mkdir -p /etc/apt/keyrings
# Download and add the key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
# Change key permissions
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "--- 3. Set up the Docker stable repository ---"
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "--- 4. Install Docker Engine and Compose Plugin ---"
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "--- 5. Start Docker service ---"
systemctl start docker
systemctl enable docker

echo "--- 6. Add current user to the docker group (to allow running without sudo) ---"
# Note: $SUDO_USER is the original username who executed the sudo command
usermod -aG docker $SUDO_USER 

echo "=========================================================="
echo "✅ Docker and Docker Compose installation complete!"
echo " "
echo "📢 Important Note:"
echo "Please log out or restart your SSH session for the new user group permissions to take effect."
echo "After logging back in, run 'docker run hello-world' for verification."
echo "=========================================================="