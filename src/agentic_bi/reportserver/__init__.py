"""Vendored Power BI Report Server access (generic, configurable).

Known zone outside the perimeter: the portal keeps its own metadata (catalog,
access grants, execution logs, favorites) in a database that belongs to the
deployment, not to this solution. Nothing here reads that database directly;
every module reaches the portal only through its public OData/REST API or works
on a `.pbix` the operator already has. Which database backs the portal, its
schema and its credentials are implementation details of a concrete installation.
"""
