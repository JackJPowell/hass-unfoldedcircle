# Dockerfile for Unfolded Circle Home Assistant Custom Component
FROM homeassistant/home-assistant:stable

# Create custom_components directory
RUN mkdir -p /config/custom_components

# Copy the custom component
COPY custom_components/unfoldedcircle /config/custom_components/unfoldedcircle

# Set proper permissions
RUN chown -R 1000:1000 /config/custom_components/unfoldedcircle

# Expose Home Assistant port
EXPOSE 8123

# Use the default Home Assistant entrypoint
# Dependencies will be installed automatically by Home Assistant when the component loads
CMD ["python", "-m", "homeassistant", "--config", "/config"]