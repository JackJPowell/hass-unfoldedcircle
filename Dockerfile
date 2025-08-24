# Dockerfile for Unfolded Circle Home Assistant Custom Component
FROM homeassistant/home-assistant:stable

# Set working directory
WORKDIR /config/custom_components

# Copy the custom component
COPY custom_components/unfoldedcircle /config/custom_components/unfoldedcircle

# Install additional requirements if any
RUN pip install --no-cache-dir \
    "websockets>=15.0,<16.0" \
    "pyUnfoldedCircleRemote==0.14.6" \
    "wakeonlan==3.1.0"

# Set proper permissions
RUN chown -R 1000:1000 /config/custom_components/unfoldedcircle

# Expose Home Assistant port
EXPOSE 8123

# Use the default Home Assistant entrypoint
CMD ["python", "-m", "homeassistant", "--config", "/config"]