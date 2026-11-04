from services.gateway.app import create_app
from services.gateway.studio_files import StudioFiles

app = create_app()
app.mount("/", StudioFiles(directory="dist", html=True), name="studio")
